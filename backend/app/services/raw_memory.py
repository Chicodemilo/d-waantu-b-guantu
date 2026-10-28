# Path: app/services/raw_memory.py
# File: raw_memory.py
# Created: 2026-09-29 (DWB-586)
# Purpose: The lesson write for human_memory mode. Appends one agent_memories
#          row, derives its tier from the moment-tags with consolidation's own
#          rule so the row is scoreable immediately, stamps the open DWB
#          session, and refuses a CALLER-SUPPLIED tier or a row with no
#          session origin.
# Caller: app/routers/agents.py (POST /api/agents/{id}/memories)
# Callees: app/services/memory_origin.require_session_origin,
#          app/services/memory_consolidate.tier_for_raw,
#          app/services/agent._record_memory_write, app/models/agent_memory
# Data In: agent_id, body, optional context_key, the section 4 moment-tags,
#          optional tier (refused)
# Data Out: dict describing the written row, including session_state
# Last Modified: 2026-10-09 (DWB-667: the write carries an author-written
#                `situation` and the keywords must MATCH it under
#                memory_consult's own predicate; previous entry:
#                DWB-649: the tier is derived AT INSERT by
#                memory_consolidate.tier_for_raw; this module no longer writes
#                `raw`, and a caller still cannot name a tier)

"""The lesson write (spec section 4), tiered at insert.

NOT app/services/agent_memory.py, which is the memory-DIRECTORY scaffolder for
stock mode and predates this feature by four months. The names are close enough
to matter: this module writes ROWS into `agent_memories`, that one writes FILES
into `.dwb/memory/`.

Spec `docs/human_memory_spec.md` section 4, verbatim: "Append RAW and unsorted
during a session. No tiering. Tiering in the moment rubber-stamps in-the-moment
salience, which is the judgment consolidation exists to make."

THIS MODULE NO LONGER WRITES `raw` (DWB-649). It builds the row, then derives
its tier by calling `memory_consolidate.tier_for_raw` on it, so a lesson is
scoreable, bandable and injectable from the moment it is written. Tier is still
NOT a caller field - a writer cannot name its own tier, and the refusal below is
unchanged. What moved is WHEN the server derives it, not WHO derives it.

WHY THAT DOES NOT CONTRADICT THE PARAGRAPH ABOVE. Section 4 forbids the MOMENT'S
OWN JUDGMENT of salience; it does not forbid a mechanical reading of the tags the
moment already recorded. `tier_for_raw` is a pure function of exactly `cost`,
`caught_by` and `surprised`. It reads nothing else - not the body, not other
rows, not the clock - and all three are written once, HERE, with no assignment
site anywhere else in the codebase. So there is no information available at
consolidation time that was not available at insert, and moving the call cannot
change its answer. The rule is still consolidation's; only its latency changed.
That latency was the entire defect: `memory_score.score` raises for `raw`, so a
row had no score and no band, so it was excluded from every candidate list, from
the moment it was written until some other job happened to run.

CORE IS STILL UNREACHABLE FROM HERE. `tier_for_raw` returns `scar` or `working`
and nothing else, and section 7 hard rule 5 keeps CORE behind a human ruling or
logged cross-context promotion evidence.

Three things here are less obvious than they look.

**`raw` IS NO LONGER A VALUE THIS MODULE WRITES, AND IT WAS NEVER NULL.**
DWB-584's ruling still governs every row that does carry it: NULL in this schema
already means "we do not know", an untiered row is a known state a writer chose,
and naming `raw` forces DWB-585's scoring query to EXCLUDE IT BY NAME where a
nullable column would let an IS NOT NULL drop those rows silently. DWB-649
changed only one thing about that - no NEW row arrives in the state. Rows written
before it are still `raw` and still need `memory_consolidate.tier_raw_memories`,
which is left in place, still called from `consolidate_agent`, and is the path a
backfill will use.

**The three moment-tags live on the MEMORY, not the journal.** Spec section 6
as amended 2026-09-29 (DWB-584). Sections 4 and 6 disagreed about where `cost`,
`caught_by` and `surprised` belonged; the tie was broken by asking what READS
each one, and all three are read against memories - section 2 gates the SCAN on
`cost`, and the SCAN runs over scars, which are memory rows.

**DWB-649 NOTE ON "CONSOLIDATION TIERS IT LATER", WHICH THIS FILE USED TO SAY
IN FOUR PLACES.** That sentence has now been wrong in two opposite directions. It was
FALSE from the day it was written until DWB-632, because nothing anywhere moved
a row out of `raw` and every row this module wrote was permanently unscoreable.
DWB-632 built `memory_consolidate.tier_raw_memories` and made it true. DWB-649
makes it OBSOLETE for new rows: the tier is derived here, at insert, so there is
no "later" to wait for and no window in which a new lesson is invisible.
`tier_raw_memories` is NOT removed and NOT dead - it still runs at session start
for the rows written before this change. But nothing this module writes depends
on it any more, so if you are reading this because a NEW row came back `raw` or
`untiered`, the insert below is the thing that is broken; consolidation is not
the thing to check.

**A WRITE WITH NO OPEN SESSION IS REFUSED (DWB-637). THIS REVERSES WHAT THIS
PARAGRAPH SAID, AND THE OLD ARGUMENT IS LEFT HERE RATHER THAN DELETED.**

It used to read: a write with no open session is ACCEPTED, because the
alternative is losing the lesson because the bookkeeping was not ready, and
section 4's whole point is that encoding is cheap and unconditional.

That is wrong on its own terms. The row it accepted had no clock origin, so
`memory_score` could not score it, so it was excluded from every candidate list
and never reached an agent. The lesson was not kept; it was lost in a way that
still counted in a row count, which is worse than losing it visibly because
nobody goes looking. And the refusal costs nothing: it writes nothing, names
the fix, and the same request succeeds once a session is open.

`memory_origin.require_session_origin` owns the rule now, for this writer and
every other. See that module for the full reasoning and for why we refuse
rather than auto-open a session.

`session_state` survives on the response, and `SESSION_OPEN` is the only value
it can now hold. It is kept rather than dropped because it is a named positive
confirmation that the row has an origin, which is the fact this endpoint exists
to guarantee; a caller reading `open` is reading a checked claim, not a default.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import (
    AgentMemory,
    MemoryCaughtBy,
    MemoryCost,
    MemoryTier,
)
from app.models.project import Project
from app.services import (
    context_scope,
    keyword_reachability,
    memory_consolidate,
    memory_origin,
)
from app.services.agent import _record_memory_write

# What the session lookup found. ONE value, because after DWB-637 there is one
# reachable outcome: a write that gets as far as returning a response has an
# open session, and a write that does not is refused before any row is built.
#
# `SESSION_NONE_OPEN = "none_open"` USED TO SIT HERE AND IS GONE DELIBERATELY.
# It named a SUCCESSFUL outcome in which the written row had no clock origin,
# which is the outage this ticket closes - a name for a bad state, sitting in
# the success path, reads as a supported mode rather than as a defect. It is
# removed rather than re-documented as unreachable so that a future caller
# cannot reach for it, and so that `session_state` has no value a consumer must
# branch on.
SESSION_OPEN = "open"  # created_session_id is that session's id


class RawMemoryWriteError(Exception):
    """Raised by append_raw_memory; the router maps `code` to a status."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


# DWB-657: the two author-supplied fields and their refusals.
#
# A WORKED EXAMPLE IS PART OF THE MESSAGE, not decoration. The caller that hits
# this is an agent mid-task that has just been refused a write it believed was
# complete; "condensed is required" tells it the name of a field it already knew
# it had omitted. What it does not know is what belongs IN the field, and that
# is the only thing that changes the next request.
_GOOD_BODY = (
    '{"body": "the full lesson in your own words", '
    '"condensed": "verify against a source you did not produce", '
    '"keywords": ["verification", "false-green"], '
    '"cost": "low", "caught_by": "me"}'
)


def _require_condensed(condensed: str | None) -> None:
    """Refuse a write whose `condensed` is missing or blank.

    NO LENGTH CAP, and that is a decision rather than an omission (DWB-654 left
    the column TEXT and assigned the policy here). A character count is a PROXY
    for "carries the lesson rather than the setup", and it is a bad one in both
    directions: it would refuse a good 200-character lesson and accept a useless
    60-character one. The error says what the line is for; nothing counts it.

    "One line" is likewise not enforced as a newline check. That one WOULD be
    mechanical rather than a proxy, but the acceptance criteria say refuse
    missing or blank and nothing more, and a newline rule would start refusing
    writes that merely wrap. Available if it is ever asked for; not built on one
    reader's interpretation.
    """
    if condensed is None or not condensed.strip():
        raise RawMemoryWriteError(
            "condensed_required",
            "condensed is required and cannot be empty or whitespace-only. It is "
            "ONE LINE CARRYING THE LESSON, NOT THE SETUP - what a future reader "
            "should do differently, not what happened to you. It exists because "
            "no extractor can produce it: an extractor surfaces what a text says "
            "most often, and what a text says most often is the setup. You are "
            "the only party who knows what the lesson is FOR. Write it as an "
            "instruction to someone who was not there. Example of an accepted "
            f"body: {_GOOD_BODY}",
        )


def _require_keywords(keywords: list[str] | None) -> None:
    """Refuse a write whose `keywords` is missing, empty, or carries a blank.

    THE BLANK-ENTRY CASE IS THE ONE WORTH READING. `len(keywords) > 0` looks
    like the obvious predicate and it passes `[""]` - a payload that means
    exactly what `[]` means, nobody supplied keywords, while answering the check
    the same way a real list does. That is the dangerous case answering
    identically to the safe one, which is the defect family this lane keeps
    producing, so the predicate is "every entry is non-blank after stripping"
    rather than "the list is non-empty".

    COUNT IS NOT ENFORCED. "Two or three" is guidance carried in the sentence
    below, because the acceptance criteria refuse missing or blank and say
    nothing about a range. One keyword and four keywords are both accepted
    today. If that is ever made a limit, this docstring and the message move
    together - they are two sentences apart on purpose.
    """
    if keywords is None or not any(k and k.strip() for k in keywords):
        raise RawMemoryWriteError(
            "keywords_required",
            "keywords is required and must contain at least one non-blank term. "
            "Send a JSON ARRAY of short strings, not a comma-joined string - the "
            "column is JSON, matching journal tags, so a keyword containing a "
            "comma needs no escaping rule. Two or three terms is the guidance: "
            "they are what a later search will MATCH ON, so prefer the words "
            "someone hunting this lesson would type over the words your body "
            f"happens to use. Example of an accepted body: {_GOOD_BODY}",
        )
    blanks = [i for i, k in enumerate(keywords) if not k or not k.strip()]
    if blanks:
        raise RawMemoryWriteError(
            "keywords_required",
            f"keywords contains blank entries at index {blanks} and every term "
            "must be non-blank. A blank entry is a placeholder someone meant to "
            "fill in, and keeping the list while dropping it would store a "
            "shorter list than you wrote without saying so. Remove the empty "
            f"entries or write the terms. Example of an accepted body: {_GOOD_BODY}",
        )


def append_raw_memory(
    db: Session,
    *,
    agent_id: int,
    body: str,
    context_key: str | None = None,
    context_free: bool = False,
    cost: str | None = None,
    caught_by: str | None = None,
    surprised: bool | None = None,
    tier: str | None = None,
    condensed: str | None = None,
    keywords: list[str] | None = None,
    situation: str | None = None,
) -> dict:
    """Append one memory row for `agent_id`, tiered from its own moment-tags.

    DWB-649: the returned row carries a real tier - `scar` or `working` - so it
    is scoreable by `memory_score` and appears in the candidate lists the moment
    this call returns. It is never `raw`. Nothing else has to run first.

    `tier` IS STILL REFUSED, and that seal is not what DWB-649 relaxed. The
    argument is accepted only so a request naming a tier can be refused WITH A
    REASON; there is no value it may hold. Section 7 hard rule 5 rules CORE out
    entirely, and section 4 rules out the rest by ruling out the WRITER'S
    judgment of its own salience. The server deriving the tier mechanically from
    the tags is a different act from the caller naming one, and only the second
    is forbidden. Silently ignoring the field would let a caller believe it had
    tiered something.

    `cost`, `caught_by` and `surprised` are section 4's moment-tags: what the
    moment knows and cannot later be reconstructed. All three are optional,
    because section 4's rule is to tag only what the moment knows - an untagged
    memory is the normal case, not a defect. `surprised` is tri-state: True,
    False and "nobody said" are three different facts, so None is not False.

    They are also now the ONLY inputs to the stored tier, which raises the cost
    of getting them wrong: an untagged row lands in `working`, and `working` is
    outside `memory_scan.SCAR_FAMILY`, so it can never fire, so
    `memory_promote.maybe_promote_scar` can never carry it to CORE. That default
    is the structural guard that stops a scratch note becoming permanent, and it
    is `tier_for_raw`'s, not a check maintained here.

    Stamps `agents.last_memory_write_at` through the same helper the stock
    memory writes use, so the DWB-519 write-on-close gate proves participation
    for a human_memory project with no mode-aware branch (see DWB-589).

    Raises RawMemoryWriteError with codes:
      - agent_not_found, agent_unscoped, project_not_found
      - empty_body
      - core_forbidden     (tier=core specifically, so the refusal cites the rule)
      - tier_not_settable  (any other tier)
      - condensed_required (DWB-657: missing, or whitespace-only)
      - keywords_required  (DWB-657: missing, empty list, or any blank entry)

    Also raises `keyword_reachability.KeywordUnreachable` (DWB-667) when
    `situation` is missing, when a keyword can never match anything, or when the
    author's own situation line does not recall its own keywords. A separate
    exception type for the same reason `MemoryOriginMissing` is one: the rule
    belongs to every writer of `agent_memories.keywords`, not to this one.

    Also raises `memory_origin.MemoryOriginMissing` (code `no_session_origin`)
    when no DWB session is open for the agent's project. A separate exception
    type rather than another code here, deliberately: the rule belongs to every
    writer of `agent_memories`, not to this one, and giving it a local code
    would let the next writer invent a second one that says the same thing in
    different words.
    """
    if tier is not None:
        # CORE gets its own code and its own sentence. The generic refusal is
        # true for it as well, but a caller reaching for `core` is reaching for
        # the one tier with a written rule behind it, and a refusal that does
        # not quote the rule teaches nothing.
        if tier == MemoryTier.core.value:
            raise RawMemoryWriteError(
                "core_forbidden",
                "tier 'core' cannot be set by this endpoint. Spec section 7 hard "
                "rule 5: CORE is never touched by automatic consolidation - only a "
                "human retires a ruled entry, and only logged cross-context "
                "evidence adds a graduated one. A write through this endpoint is "
                "neither, so there is no request shape that reaches CORE from "
                "here - the tier this endpoint derives (DWB-649) is `scar` or "
                "`working` and nothing else.",
            )
        raise RawMemoryWriteError(
            "tier_not_settable",
            f"tier '{tier}' cannot be set BY THE CALLER. Spec section 4: tiering in "
            "the moment rubber-stamps in-the-moment salience, which is the "
            "judgment consolidation exists to make. The SERVER makes it, at "
            "insert, by reading consolidation's own rule over the moment-tags you "
            f"send - cost, caught_by and surprised - and writing "
            f"'{MemoryTier.scar.value}' or '{MemoryTier.working.value}' "
            "(DWB-649: memory_consolidate.tier_for_raw). Send the tags; the tier "
            "is the server's answer to them, not yours.",
        )

    if not body or not body.strip():
        raise RawMemoryWriteError(
            "empty_body", "body is required and cannot be empty or whitespace-only"
        )

    # DWB-657. These two refusals sit HERE - after the body check, before the
    # agent lookup - so a request that cannot be stored is refused without a
    # single database read, and the caller gets the same answer whether or not
    # the agent exists.
    #
    # THE ERROR TEXT IS THE DELIVERABLE, NOT THE CHECK. The check is three
    # lines; what earns its place is the sentence, which names the field, says
    # what the field is FOR, and shows a body that would be accepted. The
    # register is `tier_not_settable` above, not `empty_body`: a refusal that
    # teaches lives next to the code, where it cannot drift away from the rule
    # it describes, and this repo has already shipped eleven sites across four
    # playbooks pointing agents at routes that 409 - nobody noticed until an
    # agent spent a write finding out.
    # ORDERING IS LOAD-BEARING AND WAS RULED ON. These two sit AFTER the body
    # check and BEFORE the agent lookup and the session-origin check below, so
    # this gate SHADOWS the no-open-session refusal for a request that is also
    # incomplete. That is deliberate. Do not swap it on the
    # surface-the-real-blocker argument, which is the reason someone will reach
    # for:
    #
    # 1. Validating before the first database read means an unstorable request
    #    costs no query, and it answers identically whether or not the agent
    #    exists - so a malformed caller learns nothing about who exists.
    # 2. THE DECIDING REASON IS WHAT EACH REFUSAL IS ACTIONABLE BY. An agent
    #    told "condensed is required" can fix that itself on the retry. An
    #    agent told "no open DWB session" can do NOTHING - opening one is
    #    TL-only. Surfacing the harder blocker first sounds right and in this
    #    system it means handing an agent a refusal it has no power over while
    #    hiding the one it does. Fixable first, unfixable second, by which
    #    point the caller has at least learned the write shape.
    #
    # The tier refusal above is upstream of both, so `{"body": x, "tier": y}`
    # still answers about the tier. That is what keeps DWB-586's tier guards
    # measuring tiers rather than quietly re-testing this gate.
    _require_condensed(condensed)
    _require_keywords(keywords)

    # DWB-667, and the ORDER HERE IS THE SAME RULING ONE STEP FURTHER ON.
    # DWB-657's two refusals ask whether the fields were SUPPLIED; these ask
    # whether what was supplied can ever be reached. Supplied-but-dead is the
    # same outcome as blank - a lesson correctly stored and never served - and
    # only the blank case was refused, which is how 288 unreachable rows came to
    # exist. They sit after 657's gate because "you sent no keywords" and "your
    # keywords cannot be recalled" are different answers and the first one is
    # the one to give when both are true.
    #
    # Still before the first database read, so an unstorable request costs no
    # query and answers identically whether or not the agent exists.
    keyword_reachability.require_situation(situation)
    # DWB-669 BEFORE DWB-667's situation check, and the order is the point. A
    # keyword made of ordinary words is MORE likely to appear in its own author's
    # situation line, not less - someone who wrote `before i` wrote "before I" in
    # the sentence beside it - so the reachability check would pass it and the
    # author would never learn it fires on everything.
    keyword_reachability.require_subject_bearing_keywords(keywords)
    keyword_reachability.require_reachable_keywords(keywords, situation)

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise RawMemoryWriteError("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        raise RawMemoryWriteError(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id - cannot resolve the open session",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise RawMemoryWriteError(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )

    # DWB-637: the precondition, not a lookup with a fallback. Raises
    # MemoryOriginMissing, which the router maps to 400; nothing has been added
    # to the session at this point, so a refusal leaves the database untouched.
    origin = memory_origin.require_session_origin(
        db, project_id=project.id, action="Memory write"
    )

    # DWB-704: a named scope that resolves to nothing is a binding the context
    # scan can never act on, which is how 424 live rows came to carry markdown
    # headings and no scar has ever concluded. Placed AFTER the origin
    # precondition because "there is no open session" blocks the write outright
    # while this only rejects one field, and before the row is built so a
    # refusal still leaves the database untouched. Absence is not refused -
    # `context_key` stays optional; see the module docstring on why an
    # unconditional gate would attach a false scope to every broad lesson.
    context_scope.require_resolvable_context(
        db, agent=agent, context_key=context_key, context_free=context_free
    )

    row = AgentMemory(
        agent_id=agent.id,
        body=body,
        context_key=context_key,
        context_free=context_free,
        cost=MemoryCost(cost) if cost is not None else None,
        caught_by=MemoryCaughtBy(caught_by) if caught_by is not None else None,
        surprised=surprised,
        # DWB-657: stored as given. Both are guaranteed non-blank by the gate
        # above, so there is no fallback here and deliberately so - a default
        # would put a line nobody wrote into a column whose whole value is that
        # an author wrote it, and it would be indistinguishable from a real one
        # at every later read.
        condensed=condensed,
        keywords=keywords,
        # DWB-667: the sentence the keywords above were checked against. Stored
        # as given, for the same reason they are - it is the provenance of this
        # row's reachability claim, and a server-written one would be
        # indistinguishable from an authored one at every later read.
        situation=situation,
        # Never conditional. `origin` is a session or this line was not reached.
        created_session_id=origin.id,
    )

    # DWB-649. The tier is derived here, and by CONSOLIDATION'S OWN FUNCTION
    # rather than a second copy of its rule: two implementations of "what earns
    # a scar" would drift, and the one that drifted would be invisible because
    # both would keep returning a valid tier.
    #
    # The row is CONSTRUCTED FIRST and the function reads it, rather than being
    # handed the three argument strings. `tier_for_raw` compares against the
    # MemoryCost / MemoryCaughtBy enums, so passing the raw strings would
    # compare a str to an enum member, which is False for every value and would
    # silently tier everything `working` - the failure would look exactly like
    # a project where nobody tags anything. Reading the built row also
    # guarantees the judgment sees the values that are about to be STORED.
    #
    # No tier is passed to the constructor above. It is set here or not at all,
    # so a future edit that drops this line fails at flush on a NOT NULL column
    # rather than quietly reinstating `raw`.
    row.tier = memory_consolidate.tier_for_raw(row)

    db.add(row)
    db.flush()

    # Same stamp the stock writes take. _record_memory_write commits, which also
    # persists the row flushed above; that is the single commit for this call.
    _record_memory_write(db, agent, datetime.now(timezone.utc))

    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "tier": row.tier.value,
        "body": row.body,
        "context_key": row.context_key,
        # DWB-704: read off the ROW rather than echoing the argument, so what
        # the caller sees is what was stored. Echoing the input would report a
        # declaration the database had not accepted.
        "context_free": row.context_free,
        "cost": row.cost.value if row.cost is not None else None,
        "caught_by": row.caught_by.value if row.caught_by is not None else None,
        "surprised": row.surprised,
        "condensed": row.condensed,
        "keywords": row.keywords,
        "situation": row.situation,
        "created_session_id": row.created_session_id,
        "session_state": SESSION_OPEN,
        "fired_count": row.fired_count,
        "created_at": row.created_at,
    }
