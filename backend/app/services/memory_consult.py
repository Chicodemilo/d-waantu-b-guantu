# Path: app/services/memory_consult.py
# File: memory_consult.py
# Created: 2026-09-30 (DWB-603, redesigned per Miles's firing ruling)
# Purpose: The consultation Miles ruled into existence - "have I made this
#          scar producing error before? Outside of normal startup." The ONLY
#          write site for AgentMemory.fired_count AND for
#          AgentMemory.last_reinforced_session_id. Requires a real
#          SITUATION, same discipline journal.search_entries already
#          enforces, and fires only the rows that MATCH it.
# Caller: whatever ends up calling a deliberate consultation (settled with
#         Barry/Freddie: not spawn/SessionStart injection, not DWB-613's
#         dashboard - both call memory_score.scored_memory(), which is pure).
#         Live caller today: hook_tracking._topoff_scar_check (DWB-612).
# Callees: app/models/agent, app/models/agent_memory,
#          app/services/dwb_session (get_active_session),
#          app/services/memory_scan (SCAR_FAMILY, imported for the scar
#          definition; the search population is CONSULTED_TIERS, defined here)
# Data In: db Session, agent_id, a situation (what the agent is doing)
# Data Out: dict {agent_id, count, entries: list[AgentMemory],
#           matched_keywords, considered, unmatchable, situation_tokens} -
#           matches already carry the post-increment fired_count and the new
#           origin
# Last Modified: 2026-10-08 (DWB-644: the match relation was backwards and
#                this feature had never fired once in production. The needle
#                is now the LESSON'S OWN KEYWORDS and the haystack is the
#                SITUATION, instead of the prompt being required to be a
#                verbatim substring of the lesson body. `match_scars` is the
#                pure half, split out so a measurement cannot fire anything;
#                previous entry: DWB-621 the recall bump)

"""Firing, moved to where Miles's ruling says it belongs.

THE RULING, VERBATIM: "Deploy doesn't count as a read. Reading is Oh have I
made this scar producing error before? Outside of normal startup." The
original DWB-603 put the write site inside `memory_score.scored_memory()`,
reasoning that `GET /memory/scored` was the only read path the store had. It
was wrong, and the audit that found it wrong found the actual seam: a read is
injection-shaped when it can be satisfied with NO QUESTION AT ALL.
`scored_memory()` can - it is "give me everything," no filter, nothing to
consult, which is exactly why it is called from BOTH spawn/SessionStart
injection and DWB-613's dashboard panel without either of those callers
needing to ask anything first. `journal.search_entries` never could: DWB-587
already refuses a filterless request, for an unrelated stated reason (the
journal must shrink while it may sprawl), but that same constraint happens to
be what makes a journal search a genuine consultation no matter what triggers
it. This module gives scars the equivalent: a search that cannot be asked with
no question in it.

WHY A SEPARATE MODULE RATHER THAN A FLAG ON `scored_memory()`. Barry's first
instinct was a `count_as_read` parameter, defaulting to fire. Archie's ruling
on that, which this module exists to honour: "a flag leaves firing reachable
from the injection path and relies on every future caller passing the right
value. Removing the call site makes injection... structurally incapable of
firing." A flag is a rule a caller can get wrong by omission; a call site that
does not exist cannot be gotten wrong at all. `scored_memory()` now contains
no code path that can ever touch `fired_count`, by construction, not by
convention.

A SITUATION IS REQUIRED, NO BLANKET MATCH. Same reasoning as
`journal.search_entries`' filter requirement, applied to the actual defect this
module exists to avoid repeating: a consultation with no situation in it is a
list wearing a consultation's clothes, and would reopen exactly the hole this
ticket closed. Refused the same way journal refuses an unfiltered read.

DWB-644 CHANGED WHAT IS COMPARED, NOT WHETHER A QUESTION IS REQUIRED. The
refusal above survived the inversion unchanged; what moved is which side is the
needle. See the long note above `_SITUATION_STOPWORDS` for the measurement that
forced it - this consultation had fired exactly zero times in production across
877 rows, and the same comparison could also fire on an ordinary English
phrase.

ONLY A MATCH FIRES. Section 5's principle, carried over: a match is literal
evidence the agent has been here before (Archie's framing of Miles's own
words). A search that found nothing is not evidence of anything, so a scar
that was searched FOR and not found gets no increment - approaching the
question and getting a negative answer does not count as having asked it
successfully.

DWB-668 CHANGED WHICH TIERS ARE SEARCHED, NOT WHAT A MATCH MEANS. This used to
be scoped to `memory_scan.SCAR_FAMILY`, on the reasoning that there is exactly
one definition of "what is a scar" and this module should import it rather than
keep a second one that could drift. That reasoning is intact and SCAR_FAMILY is
still the one definition of a scar. What it could not express is that "what a
consultation searches" is a DIFFERENT question which happened to have the same
answer - and while it had the same answer, promotion to CORE removed a lesson
from the only path that could ever recall it. The search population now has its
own name, `CONSULTED_TIERS`, defined below with the measurement that forced it.
"""

import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import dwb_session as session_svc
from app.services.memory_scan import SCAR_FAMILY

# DWB-668: WHAT A CONSULTATION SEARCHES. Its own concept, its own name, in the
# module that owns consultation - NOT a widening of `memory_scan.SCAR_FAMILY`.
#
# The tempting one-line fix was to add `core` to SCAR_FAMILY. That constant
# answers "what is a scar", it has exactly one definition on purpose, and
# DWB-611 collapsed two scar tiers into one specifically to stop a second tier
# list drifting from the first. "What gets searched" is a different question
# that happens to have had the same answer, and the day the two diverge is the
# day a tier silently joins or leaves the scar family because somebody wanted
# it findable. `SCAR_FAMILY` is still imported and still used - by the firing
# tests and by everything that genuinely means "is this a scar".
#
# WHY CORE IS IN HERE. Before this ticket `consult_scars` searched scars only,
# so promotion to CORE - the reward for a lesson that proved itself three times
# - REMOVED THE LESSON FROM THE ONLY PATH THAT COULD EVER RECALL IT AGAIN.
# Combined with the absence of a demote path (DWB-665), a promoted row could not
# decay, could not be recalled, could not be corrected by use and could not be
# demoted. Measured: 126 CORE rows across the project, 86 on one agent, every
# one of them unreachable. Archie's ruling, 2026-10-09: "a memory tier whose
# contents can never be recalled is not a memory tier."
#
# ORDER IS NOT SIGNIFICANCE. This tuple is a membership test in a SQL `IN`,
# not a ranking. Nothing here scores or orders by tier, and a reader looking
# for CORE-first behaviour will not find it because there is none.
CONSULTED_TIERS: tuple[MemoryTier, ...] = (MemoryTier.core, MemoryTier.scar)

# WHAT A CORE ROW'S `fired_count` MEANS, because a counter with a writer and no
# consumer is the DWB-603 defect returning by a different door.
#
# A CORE row that matches a situation increments `fired_count` and moves
# `last_reinforced_session_id`, exactly as a scar does. Neither changes its
# score - CORE's curve is flat at 10 in every bucket - and that is the point
# rather than a problem: the count is not feeding the decay model, it is the
# only record that a CORE row has ever been used for anything. DWB-665's
# demotion ruling rests on it; without it, a human asked whether a CORE row
# deserves its tier has nothing to look at.
#
# `maybe_promote_scar` cannot be reached by a CORE row - it raises `not_a_scar`
# for any tier outside SCAR_FAMILY, and `memory_consolidate` only ever hands it
# scar-family candidates - so firing a CORE row cannot re-promote it and there
# is no second trigger to guard.
#
# THERE IS DELIBERATELY NO AUTOMATIC DEMOTION NOMINATION KEYED ON THIS COUNT,
# and the next person will want to build one, so here is why not. The obvious
# rule is "a CORE row still at fired_count 0 after N sessions is a demotion
# candidate". On the day DWB-668 shipped, all 126 CORE rows read 0 - because
# the tier was unsearchable, not because the rows were bad. That rule would
# have nominated the entire tier on its first run and would have been measuring
# this ticket's bug rather than the rows. The safe case and the dangerous case
# answer identically, which is the shape this lane keeps finding.
#
# A real version needs a clock that starts WHEN THE TIER BECAME SEARCHABLE, and
# nothing records that. Not `created_session_id` (when the row was written),
# not `last_reinforced_session_id` (null on every one of them). Adding that
# clock is the prerequisite, not the nomination rule.


class ConsultError(Exception):
    """Raised by this module; the router (once one exists) maps `code` to a
    status, same pattern as every other service error class in this lane."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _active_session_id(db: Session, agent_id: int) -> int | None:
    """The DWB session this consultation is happening inside, or None.

    Same resolution journal.py uses for its own rows: agent -> project ->
    active session. None is a legitimate answer, not an error - DWB-586 accepts
    writes when no session is open, so a consultation can genuinely happen
    outside one. What None must NOT do is clear an origin that is already
    there; see `_fire`.
    """
    agent = db.get(Agent, agent_id)
    if agent is None or agent.project_id is None:
        return None
    active = session_svc.get_active_session(db, agent.project_id)
    return active.id if active is not None else None


def _fire(
    db: Session, memory_ids: list[int], *, reinforce_session_id: int | None = None
) -> None:
    """THE ONLY WRITE SITE FOR `fired_count` AND `last_reinforced_session_id`.

    A single UPDATE, not a loop - same shape journal.py's own write site uses
    for its counter, for the same reason: one statement is what lets a guard
    test assert "exactly one write site" and mean it. `synchronize_session=
    "fetch"` expires the matching ORM objects, so a caller holding those rows
    (consult_scars does, immediately after this call) reads the POST-increment
    value rather than the stale one already in the session's identity map.

    DWB-621: THE RECALL BUMP. Miles's ruling is that a scar which is recalled
    returns to full strength. The whole of that is moving the decay clock's
    origin to the session the recall happened in: `sessions_since_reinforced`
    already does COALESCE(last_reinforced, created), so a fresh origin means
    zero sessions elapsed, which the existing curve already scores 10. There is
    deliberately NO new scoring path - a second mechanism for one outcome is
    how two of them end up disagreeing.

    WHY A SELF-ASSIGNMENT RATHER THAN A SECOND `.values()` CALL. With no
    session open there is nothing to move the origin to, and writing NULL would
    fall back through that COALESCE to `created_session_id`, which is OLDER:
    the row would come out of a consultation scoring LOWER than it went in,
    which is the opposite of the ruling. Branching into two `update()` calls
    would fix that and break something else - each branch is a separate
    `fired_count=` keyword, so the "exactly one write site" guard would start
    counting two and the next person would weaken the guard to make it pass.
    `SET col = col` is a true no-op in SQL and keeps both fields written in
    exactly one place.
    """
    if not memory_ids:
        return
    new_origin = (
        AgentMemory.last_reinforced_session_id
        if reinforce_session_id is None
        else reinforce_session_id
    )
    db.execute(
        update(AgentMemory)
        .where(AgentMemory.id.in_(memory_ids))
        .values(
            fired_count=AgentMemory.fired_count + 1,
            last_reinforced_session_id=new_origin,
        )
        .execution_options(synchronize_session="fetch")
    )


# DWB-644: THE RELATION, AND WHY IT IS THIS WAY ROUND.
#
# Until this ticket the needle was the USER'S PROMPT and the haystack was the
# LESSON: `AgentMemory.body LIKE '%' || prompt || '%'`. That is backwards, and
# it was wrong in both directions at once rather than merely too strict.
#
#   - It could not fire when it should. A scar matched only when the whole
#     prompt was a verbatim substring of the lesson body, which happens only
#     when the user is RECITING THE LESSON BACK - exactly the moment a
#     consultation is unnecessary. `fired_count` was 0 on all 877 rows across
#     both human_memory projects, with 0 non-null `last_reinforced_session_id`.
#   - It could fire when nothing happened. A short common English phrase
#     ('one at a time', 'the same thing') is a substring of real lesson bodies,
#     so typing one as a whole prompt fired scars nobody recalled. At
#     SCAR_FIRED_THRESHOLD that promotes a row to CORE, which never decays and
#     has no demotion path (DWB-665).
#
# NO CONSTANT MOVES THAT. Both directions are the same comparison, so lowering
# the prompt-length floor widens coincidence without helping recall, and
# raising it narrows both identically. The relation itself had to be inverted.
#
# SO: THE NEEDLE IS THE LESSON'S OWN KEYWORDS AND THE HAYSTACK IS THE PROMPT.
# `keywords` is author-supplied by DWB-654/657 and is defined as "the words
# someone hunting this lesson would type" - which is a description of the
# retrieval term for exactly this search. The lesson now says what it is about
# and the situation is tested against that, rather than the situation being
# required to quote the lesson.
#
# Consequences worth naming because they are not obvious:
#   - The body is no longer searched at all. Nothing here reads the lesson
#     text, which also means nothing here can be fired by prose the author did
#     not choose as a retrieval term.
#   - Matching moved from SQL to Python. The `utf8mb4_0900_ai_ci` collation
#     made the old LIKE case-insensitive for free; `_tokenize` now casefolds
#     EXPLICITLY, because an implicit property of a column is not available
#     when the needle lives in a JSON list rather than in a column predicate.
#     The set is bounded by construction - one agent's scars, indexed on
#     (agent_id, tier) - so this is a few dozen rows, not a scan.
#   - Nothing user-authored is stored or returned. The old code echoed the
#     prompt back as `term`; this returns matched KEYWORDS, which the agent
#     wrote, and a token COUNT. That is the whole measurement surface
#     (DWB-644 criterion 3) and it needs no user text to work.

# Tokens that carry no retrieval signal. Deliberately a SHORT NAMED SET rather
# than a stopword corpus or a length rule: 'ci', 'db' and 'rc' are two letters
# and are exactly the sort of term an author picks on purpose, so a length cut
# would delete the signal it was meant to protect. Every member here is a word
# that (a) appears in ordinary prose often enough that its presence in a prompt
# is no evidence of anything, and (b) actually occurs inside author-written
# keyword phrases in the live store ('naming vs counting', 'code-not-docs',
# 'is not the same'), where leaving it in would require the user to type a
# joining word to get a match.
_SITUATION_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
        "is", "it", "no", "not", "of", "on", "or", "that", "the", "this",
        "to", "vs", "with",
    }
)

# How many distinct keyword TOKENS a situation must hit before the lesson is
# treated as recalled. Tokens, not keywords, and that distinction was settled by
# measurement against the live store rather than by taste.
#
# TWO, AND THE CONJUNCTION IS THE ENTIRE MECHANISM. One shared ordinary word is
# coincidence. Measured over one agent's 109 live scars, a prompt of 'run the
# tests' hits the bare keyword 'tests' on 7 unrelated lessons, 'verification'
# hits 9, and 'check the state of the ticket' hits 'ticket' on 4. Those are the
# false-fire channel this ticket exists to close, wearing better words. Two
# distinct words co-occurring is evidence about the situation.
#
# COUNTED ACROSS KEYWORDS, NOT WITHIN ONE, so both honest shapes qualify: one
# two-word keyword fully present ('working tree', 'git checkout', 'code
# review'), or two separate single-word keywords both present. In the same
# measurement every multi-token hit was the right lesson and almost every
# single-token hit was not.
#
# WHAT IT COSTS, STATED RATHER THAN DISCOVERED LATER: a lesson keyworded only
# with bare single words is recalled only when two of them appear together, and
# a lesson whose keyword tokens number fewer than two in total can never be
# recalled at all. The second case is reported as `unmatchable` rather than
# counted as a miss. One genuine recall was lost to this rule in measurement
# ('cmp', a rare one-word keyword naming exactly one lesson). Firing on a single
# token when that token is unique in the agent's corpus would recover it and is
# deliberately NOT built here: it is one observed instance, it needs a second
# guard for a small corpus where every token is unique, and DWB-644 is about
# making the relation correct rather than tuning its recall. Raised as a
# follow-up with that measurement attached rather than built on one case.
_MATCH_TOKENS_REQUIRED = 2

# Split on anything that is not a letter or digit, so 'code-not-docs' and
# 'code not docs' tokenize identically and an author's hyphen style cannot
# decide whether their lesson is reachable.
_TOKEN_SPLIT = re.compile(r"[^0-9a-z]+")


def _tokenize(text: str) -> frozenset[str]:
    """Casefold, split on non-alphanumerics, drop empties.

    EXPLICIT casefold, see the module note above: this comparison used to
    inherit case-insensitivity from the column's collation, and a Python
    reimplementation that forgets it understates matches in one direction only
    (always fewer), which no consistency check between two such
    reimplementations can catch - they agree.
    """
    if not text:
        return frozenset()
    return frozenset(t for t in _TOKEN_SPLIT.split(text.casefold()) if t)


def _keyword_tokens(keyword: object) -> frozenset[str]:
    """The tokens a single keyword requires, stopwords removed.

    Returns an empty set for a non-string, a blank, or a keyword made entirely
    of stopwords. `matching_keywords` treats empty as NO MATCH rather than as a
    trivially-satisfied one: a requirement with nothing in it is satisfied by
    every situation, which would fire the row on an empty prompt. That is the
    vacuous-assertion shape, and it is the one place this design could have
    reintroduced a blanket match.
    """
    if not isinstance(keyword, str):
        return frozenset()
    return frozenset(t for t in _tokenize(keyword) if t not in _SITUATION_STOPWORDS)


def keyword_token_set(memory: AgentMemory) -> frozenset[str]:
    """Every token any of this memory's keywords could be matched on.

    The reachability question: a memory whose whole keyword set contributes
    fewer than `_MATCH_TOKENS_REQUIRED` tokens cannot satisfy the rule whatever
    the situation says, so `match_scars` counts it as `unmatchable` rather than
    silently reporting it as searched-and-not-found. Those are different facts
    and only one of them is about the situation.
    """
    tokens: set[str] = set()
    for k in memory.keywords or []:
        tokens |= _keyword_tokens(k)
    return frozenset(tokens)


def usable_keywords(memory: AgentMemory) -> list[str]:
    """This memory's keywords that can ever match anything.

    Named and returned rather than filtered silently, because the rows this
    excludes are a REAL HOLE and a silent one would be invisible: 15 live scars
    predate DWB-657 and carry no keywords at all, so under this relation they
    can never fire. They are reported as `unmatchable` by `match_scars` instead
    of quietly counting as "searched and not found". The hole closes on its own
    as those rows decay, because DWB-657 makes keywords required on every new
    write; what must not happen is a body-derived backfill, which DWB-654 rules
    out in plain words - nothing in this lane may populate `keywords` from the
    body.
    """
    return [k for k in (memory.keywords or []) if _keyword_tokens(k)]


def matched_tokens(
    memory: AgentMemory, situation_tokens: frozenset[str]
) -> frozenset[str]:
    """The distinct tokens this situation hit, across every matching keyword.

    This is the quantity `_MATCH_TOKENS_REQUIRED` is counted against. DISTINCT,
    so a lesson repeating a word across two keywords ('stale comment', 'stale
    doc') cannot reach the floor on one word typed once.
    """
    hit = matching_keywords(memory, situation_tokens)
    if not hit:
        return frozenset()
    tokens: set[str] = set()
    for k in hit:
        tokens |= _keyword_tokens(k)
    return frozenset(tokens)


def matching_keywords(memory: AgentMemory, situation_tokens: frozenset[str]) -> list[str]:
    """Which of this memory's keywords the situation contains, in order.

    A keyword matches when EVERY token it needs is present. Partial credit
    inside a keyword was considered and rejected: 'stale inbox file' matching on
    'file' alone is the single-common-word rule again, one level down.
    """
    if not situation_tokens:
        return []
    return [
        k
        for k in (memory.keywords or [])
        if (tokens := _keyword_tokens(k)) and tokens <= situation_tokens
    ]


def match_scars(db: Session, *, agent_id: int, situation: str) -> dict:
    """WHICH SCARS THIS SITUATION RECALLS. PURE - WRITES NOTHING.

    Split out from `consult_scars` deliberately, and it is the same ruling that
    moved firing out of `scored_memory()` in the first place: a flag is a thing
    a future caller gets wrong by omission, where a function with no write in it
    is structurally incapable of firing no matter who calls it. The measurement
    harness for DWB-644 criterion 3 calls THIS, so an instrument pointed at the
    live store cannot promote anything to CORE by running.

    Returns the three numbers a measurement needs next to the matches
    themselves: how many rows were `considered`, how many were `unmatchable`
    (fewer than `_MATCH_TOKENS_REQUIRED` keyword tokens in total, so they could
    not have matched whatever the situation said), and how many tokens the
    situation contributed. A count with no population beside it is not comparable to
    anyone else's count.
    """
    if not situation or not situation.strip():
        raise ConsultError(
            "situation_required",
            "a consultation requires a real situation - 'have I made this "
            "error before' is a question, and a blank situation asks nothing. "
            "Describe what you are doing; the lesson's own keywords are "
            "matched against it.",
        )

    tokens = _tokenize(situation)
    candidates = list(
        db.execute(
            select(AgentMemory)
            .where(
                AgentMemory.agent_id == agent_id,
                AgentMemory.tier.in_(CONSULTED_TIERS),
            )
            .order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )

    matches: list[AgentMemory] = []
    hits: dict[int, list[str]] = {}
    unmatchable = 0
    for memory in candidates:
        if len(keyword_token_set(memory)) < _MATCH_TOKENS_REQUIRED:
            unmatchable += 1
            continue
        if len(matched_tokens(memory, tokens)) >= _MATCH_TOKENS_REQUIRED:
            matches.append(memory)
            hits[memory.id] = matching_keywords(memory, tokens)

    return {
        "agent_id": agent_id,
        "count": len(matches),
        "entries": matches,
        "matched_keywords": hits,
        "considered": len(candidates),
        "unmatchable": unmatchable,
        "situation_tokens": len(tokens),
    }


def consult_scars(db: Session, *, agent_id: int, situation: str) -> dict:
    """The deliberate consultation: "have I made this scar producing error
    before?" Every scar this SITUATION recalls has its `fired_count`
    incremented and its decay clock reset; nothing else is touched.

    DWB-644 RENAMED THE PARAMETER FROM `term` TO `situation`, ON PURPOSE. The
    argument used to be a slice of the user's prompt used as a literal
    substring to find inside a lesson; it is now a description of what is
    happening, which the lesson's own keywords are tested against. Those are
    different questions, and a caller that keeps passing `term=` gets a
    TypeError rather than a silently reinterpreted argument. Same reason the
    old name could not simply be kept: the dangerous failure here is a call
    site that still means the old thing and still runs.

    Refuses a blank or missing situation the same way `journal.search_entries`
    refuses a filterless request - see the module docstring on why that
    refusal is the actual mechanism, not a formality borrowed from journal.py.

    Returns `match_scars`' dict unchanged, with `entries` carrying the matched
    rows POST-increment: `_fire`'s `synchronize_session="fetch"` expires them,
    so a caller reading `entries[i].fired_count` sees the value AFTER this
    call. `count` and `entries` are the two handles DWB-612's wiring already
    pulls off journal.search_entries' response; they survived the inversion so
    that wiring did not have to change shape.

    Does not commit; the caller owns the transaction, same convention as
    every other service function in this lane.
    """
    result = match_scars(db, agent_id=agent_id, situation=situation)

    _fire(
        db,
        [m.id for m in result["entries"]],
        reinforce_session_id=_active_session_id(db, agent_id),
    )
    db.flush()

    return result
