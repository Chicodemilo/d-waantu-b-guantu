# Path: app/services/memory_fill.py
# File: memory_fill.py
# Created: 2026-10-08 (DWB-664)
# Purpose: Two owner-only operations on an EXISTING agent_memories row, and
#          nothing else on it. `fill_memory` completes a missing `condensed`,
#          `keywords` or `situation`, under the same gates as a fresh write;
#          `rekey_memory` (DWB-667) REPLACES a dead keyword set and never
#          touches `condensed`.
# Caller: app/routers/agents.py (POST /{agent_id}/memories/{memory_id}/fill,
#         POST /{agent_id}/memories/{memory_id}/rekey)
# Callees: app/services/raw_memory._require_condensed / _require_keywords,
#          app/services/keyword_reachability, app/models/agent_memory
# Data In: agent_id, memory_id, acting agent id, the fields being written
# Data Out: dict describing the row afterwards, including the history
#           fields the caller can check were untouched
# Last Modified: 2026-10-09 (DWB-664: `situation` is fillable and the fill of
#                `keywords` now runs DWB-667's reachability gate and DWB-669's
#                subject rule, which this route had been a hole through)

"""Complete a memory that predates `condensed` and `keywords` (DWB-664).

WHY A ROUTE AND NOT A SCRIPT. ~820 rows predate the columns, and Miles's ruling
is that the lines are AUTHORED, not derived. A script would have to generate
them, and an extractor surfaces what a text says most often, which is the SETUP.
So each agent fills its own, and this is the surface it uses.

WHY NOT WITHDRAW-AND-REPOST, which is the only thing that was possible before:
it destroys the row. `id`, `created_at`, `fired_count`,
`last_reinforced_session_id` and every `memory_transitions.target_memory_id`
pointing at it all go. Changing one label must not cost a row its history.

FOUR REFUSALS, AND EACH IS A DIFFERENT CLAIM.

  OWNER ONLY (403). The acting agent must BE the row's agent. The premise of
  the whole lane is author-supplied; a route that lets anyone fill anyone's
  line is machine authorship wearing a human's name, and it would be
  indistinguishable afterwards from the real thing.

  FILL-ONLY, NOT EDIT (409). A field that already carries a value is refused.
  This exists to COMPLETE rows that predate the columns, not to let an agent
  revise its own history once it knows how the story ended. A second thought
  about an old lesson is a NEW lesson and belongs in a new row, where its own
  created_at says when it was had.

  BLANK (400). Same validators as the write gate, imported rather than
  reimplemented - see below.

  NOTHING TO DO (400). A request naming no field is refused rather than
  silently succeeding, because a 200 that changed nothing is the shape this
  whole lane keeps finding.

  UNREACHABLE (400). Filling `keywords` goes through the SAME two gates a
  fresh write goes through - DWB-667's reachability check and DWB-669's subject
  rule - which is why `situation` is a third fillable field here. See THE
  KEYWORD HALF below; this route shipped before those gates existed and was
  writing rows that `/memories` would have refused.

THE KEYWORD HALF IS A PAIR, NOT A FIELD. `keywords` and `situation` are the
index and the sentence the index was demonstrated against, and DWB-667's whole
mechanism is that the second is checked against the first with the comparison
retrieval will later use. So filling keywords with no situation is not a
partial fill, it is an incoherent one: it stores a pointer nobody ever showed
could be followed. This route therefore requires a situation to be AVAILABLE
when keywords are filled - sent in the same request, or already on the row -
and runs both gates before assigning anything.

Without that, fill was a hole straight through both gates: it could write
keywords that are unreachable from any sentence, or made entirely of words
naming no subject, onto a row that `POST /memories` would have refused outright.
A route that can store what the write gate rejects makes the write gate
advisory, and the rows it produces are indistinguishable afterwards from ones
written properly.

FILLING `situation` ALONE RUNS REACHABILITY BUT NOT THE SUBJECT RULE, and the
asymmetry is deliberate rather than an oversight. Reachability is about the
PAIR, so a new sentence that cannot recall the keywords already on the row is an
incoherent pair and is refused, with the message naming `rekey` - the one route
that can replace both halves together. The subject rule is about the KEYWORDS
ALONE, and those keywords are already set, so fill refuses to touch them with
`already_set`. Enforcing it here would strand the row: refused for a defect this
route has no power to repair. Rekey runs that rule, and rekey is where such a
row belongs.

PER-FIELD RATHER THAN BOTH-OR-NOTHING, which is a deliberate choice. Refusing
the whole request when EITHER field is already set would make a half-filled row
permanently unfillable: a row with `condensed` and no `keywords` could never
get its keywords, and the only route out would be the withdraw-and-repost this
ticket exists to avoid. So each field is judged on its own, and a request may
carry one or both.

THE VALIDATORS ARE IMPORTED, NOT COPIED, AND NOT RENAMED. `_require_condensed`
and `_require_keywords` live in `raw_memory` because the write gate got there
first. Importing a module-private name across the package is the lesser evil:
a second implementation of "what counts as blank" would drift, and the drift
would be INVISIBLE because both copies keep returning a valid-looking answer -
one route would accept `[""]` and the other refuse it, and nobody would see it
until the data disagreed with itself. Renaming them to public would touch
DWB-657's gate and its tests for no behavioural gain, so the import carries this
comment instead.

They raise `RawMemoryWriteError`, which is also deliberate: a caller that sends
a blank `condensed` here gets the SAME code and the SAME sentence it would get
from the write gate, because it broke the same rule.

DWB-667 ADDED A SECOND OPERATION TO THIS MODULE THAT REPLACES RATHER THAN
FILLS, AND THE PARAGRAPHS ABOVE STILL STAND. `rekey_memory` overwrites
`keywords` and cannot touch `condensed` - not by convention, but because the
field is not a parameter, the request schema forbids the key, and there is no
assignment to it in that function. The fill-not-edit argument is an argument
about `condensed`: it is THE LESSON, and revising it once you know how the story
ended is revising what you learned. Keywords are an INDEX. They make no claim
about the past, so repairing one is not revising history, and 288 live scars
needed repairing precisely because the fill route refuses every one of them with
`already_set`. See that function for the full reasoning and for why it is still
owner-only.
"""

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory
from app.services import keyword_reachability
from app.services.raw_memory import (  # noqa: F401 - see module docstring
    _require_condensed,
    _require_keywords,
)

# Sentinel: "the caller did not mention this field", which is different from
# "the caller sent null". A bare None cannot express that difference, and the
# difference is the whole of per-field filling.
UNSET = object()


class MemoryFillError(Exception):
    """Raised when a fill is refused. The router maps `code` to a status."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _is_set(value) -> bool:
    """Does this column already CARRY something.

    Blank counts as NOT set, matching the validators' own notion of blank: a
    `""` or a `[]` or a `[""]` carries nothing, and refusing to fill over it
    would strand a row on a value that means "nobody supplied this". Those
    states are unreachable through the API - the write gate refuses them - but
    they are storable, and a backfill is exactly the kind of thing that
    produces one.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(k and str(k).strip() for k in value)
    return True


def _require_owned_memory(
    db: Session,
    *,
    agent_id: int,
    memory_id: int,
    acting_agent_id: int | None,
) -> AgentMemory:
    """The row, or a refusal. ONE definition of "you own this", for both ops.

    Extracted in DWB-667 when `rekey_memory` arrived and needed the identical
    three refusals. A second copy would have drifted, and the drift would be
    invisible in the worst direction: one route would keep enforcing ownership
    while the other quietly stopped, and both would keep returning plausible
    answers. The premise of this whole lane is that the author wrote it; a route
    that lets anyone write anyone's row is machine authorship wearing a human's
    name, and it is indistinguishable afterwards from the real thing.

    Ordering is deliberate and unchanged from DWB-664. Wrong-agent is checked
    BEFORE ownership, so a caller aiming at the wrong agent is told which fact
    is wrong rather than being told it does not own a row that was never on the
    agent it named. Same order as withdraw.
    """
    memory = db.get(AgentMemory, memory_id)
    if memory is None:
        raise MemoryFillError("memory_not_found", f"memory id {memory_id} not found")

    if memory.agent_id != agent_id:
        raise MemoryFillError(
            "memory_not_on_agent",
            f"memory {memory_id} belongs to agent {memory.agent_id}, not agent "
            f"{agent_id}",
        )

    if acting_agent_id is None:
        raise MemoryFillError(
            "actor_required",
            "X-Agent-ID is required: a condensed line and a keyword set are "
            "AUTHORED, and an unattributed one is exactly the machine-written "
            "summary those fields exist instead of.",
        )
    if acting_agent_id != memory.agent_id:
        actor = db.get(Agent, acting_agent_id)
        actor_name = actor.name if actor is not None else f"id {acting_agent_id}"
        raise MemoryFillError(
            "not_owner",
            f"{actor_name} cannot write the condensed line or the keywords for "
            f"a memory belonging to agent {memory.agent_id}. Only the owning "
            "agent may: the condensed line says what the lesson is FOR, and the "
            "keywords say which words will be in the air when it is needed. "
            "Only the agent that learned it knows either. Someone else writing "
            "them is a summary by a stranger, and it would be "
            "indistinguishable from the real thing afterwards.",
        )
    return memory


def fill_memory(
    db: Session,
    *,
    agent_id: int,
    memory_id: int,
    acting_agent_id: int | None,
    condensed=UNSET,
    keywords=UNSET,
    situation=UNSET,
) -> dict:
    """Set `condensed`, `keywords` and/or `situation` on one row. No commit.

    Only those three fields are ever assigned. There is no code path here that
    writes `body`, `tier`, the moment-tags, either session id, `fired_count` or
    `source_journal_id` - which is the point, and is asserted structurally in
    tests/test_memory_fill_dwb664.py rather than left to review.

    `tier` deserves naming on its own: `memory_decide.decide` refuses to let an
    agent grant itself CORE, on the grounds that only a human does that. A
    route that accepted a tier here would be a side door to the one decision
    the design puts behind a person.

    Raises MemoryFillError with codes:
      - memory_not_found      (404)
      - memory_not_on_agent   (400)
      - actor_required        (400)
      - not_owner             (403)
      - nothing_to_fill       (400)
      - situation_required    (400)
      - already_set           (409)
    plus `raw_memory.RawMemoryWriteError` for a blank value and
    `keyword_reachability.KeywordUnreachable` for a keyword set that cannot be
    reached or carries no subject - both unchanged from the write gate, because
    the same rule was broken.
    """
    memory = _require_owned_memory(
        db, agent_id=agent_id, memory_id=memory_id, acting_agent_id=acting_agent_id
    )

    wants_condensed = condensed is not UNSET
    wants_keywords = keywords is not UNSET
    wants_situation = situation is not UNSET
    if not wants_condensed and not wants_keywords and not wants_situation:
        raise MemoryFillError(
            "nothing_to_fill",
            "send `condensed`, `keywords`, `situation`, or any combination of "
            "them. A request naming none would return 200 having changed "
            "nothing, which is the silent success this lane keeps finding.",
        )

    # Refusals BEFORE any assignment, so a request that is going to be refused
    # leaves the row untouched even in the session's identity map.
    if wants_condensed and _is_set(memory.condensed):
        raise MemoryFillError(
            "already_set",
            f"memory {memory_id} already has a condensed line, and this route "
            "fills rather than edits. It exists to complete rows written before "
            "the field did, not to revise a lesson after the fact. If you have "
            "thought again about this one, that is a NEW lesson: write it as a "
            "new memory, where its own created_at says when you had it.",
        )
    if wants_keywords and _is_set(memory.keywords):
        raise MemoryFillError(
            "already_set",
            f"memory {memory_id} already has keywords, and this route fills "
            "rather than edits. See the condensed refusal for the reasoning; a "
            "revised keyword set is a revision, and revisions belong in a new "
            "row. To REPLACE a keyword set that cannot be reached, use "
            "`/rekey`, which exists for exactly that and checks the "
            "replacement against a situation.",
        )
    if wants_situation and _is_set(memory.situation):
        raise MemoryFillError(
            "already_set",
            f"memory {memory_id} already has a situation line, and this route "
            "fills rather than edits. A situation is the sentence its keywords "
            "were demonstrated against, so replacing it means re-demonstrating "
            "the pair: send both to `/rekey` instead.",
        )

    if wants_condensed:
        _require_condensed(condensed)
    if wants_keywords:
        _require_keywords(keywords)

    # THE TWO GATES, IN THE SAME ORDER `raw_memory.append_raw_memory` RUNS
    # THEM, because a row filled here must be one the write gate would have
    # accepted. Before DWB-667 and DWB-669 this route had neither, so it could
    # store keywords that no sentence can reach and keywords made entirely of
    # words naming no subject - onto rows `POST /memories` refuses outright.
    #
    # The situation may arrive in THIS request or already be on the row. Both
    # are a real fill of an incomplete row; what is not allowed is keywords
    # with no sentence anywhere, because that stores a pointer nobody ever
    # showed could be followed.
    effective_situation = situation if wants_situation else memory.situation
    if wants_keywords:
        if not _is_set(effective_situation):
            raise MemoryFillError(
                "situation_required",
                f"memory {memory_id} has no situation line, so keywords sent "
                "on their own cannot be checked and will not be stored. Send "
                "`situation` in the same request: ONE LINE, in your own words, "
                "naming the moment this lesson applies. Your keywords are "
                "matched against it with the SAME comparison that later decides "
                "whether this lesson is recalled, which is the only thing that "
                "makes a keyword set more than a filing label.",
            )
        keyword_reachability.require_situation(effective_situation)
        # DWB-669 before DWB-667's reachability check, matching the write gate:
        # a keyword made of ordinary words is MORE likely to appear in its own
        # author's sentence, so reachability would pass it and the author would
        # never learn it fires on everything.
        keyword_reachability.require_subject_bearing_keywords(keywords)
        keyword_reachability.require_reachable_keywords(keywords, effective_situation)
    elif wants_situation:
        keyword_reachability.require_situation(situation)
        # The PAIR must be coherent, so a new sentence that cannot recall the
        # keywords already on the row is refused. The SUBJECT rule deliberately
        # does not run here: those keywords are already set, this route refuses
        # to touch them, and enforcing a rule against a value it cannot repair
        # would strand the row. `/rekey` replaces both halves together and runs
        # both rules; the refusal below names it.
        if _is_set(memory.keywords):
            try:
                keyword_reachability.require_reachable_keywords(
                    list(memory.keywords), situation
                )
            except keyword_reachability.KeywordUnreachable as exc:
                # Same type and same code, so a caller branching on either is
                # unaffected and the write gate's own words still arrive intact.
                # One sentence is appended because this refusal has a different
                # remedy from the write gate's: there, you rewrite the keywords
                # you are about to send; here, they are already stored and this
                # route cannot touch them.
                raise keyword_reachability.KeywordUnreachable(
                    exc.code,
                    f"{exc.detail} NOTE: these keywords are already stored on "
                    f"memory {memory_id} and `/fill` cannot replace them. If the "
                    "sentence above is the honest one, the keywords are what is "
                    "wrong: send both to `/rekey`, which replaces the pair "
                    "together.",
                ) from exc

    # THE ONLY THREE ASSIGNMENTS IN THIS MODULE'S FILL PATH.
    if wants_condensed:
        memory.condensed = condensed
    if wants_keywords:
        memory.keywords = keywords
    if wants_situation:
        memory.situation = situation
    db.flush()

    return {
        "memory_id": memory.id,
        "agent_id": memory.agent_id,
        "condensed": memory.condensed,
        "keywords": memory.keywords,
        "situation": memory.situation,
        "filled": [
            name
            for name, wanted in (
                ("condensed", wants_condensed),
                ("keywords", wants_keywords),
                ("situation", wants_situation),
            )
            if wanted
        ],
        # Echoed back so the CALLER can see its history survived, rather than
        # taking it on trust. These are the fields withdraw-and-repost would
        # have destroyed, which is why this route exists at all.
        "tier": memory.tier.value,
        "created_at": memory.created_at,
        "fired_count": memory.fired_count,
        "created_session_id": memory.created_session_id,
        "last_reinforced_session_id": memory.last_reinforced_session_id,
        "source_journal_id": memory.source_journal_id,
    }


def rekey_memory(
    db: Session,
    *,
    agent_id: int,
    memory_id: int,
    acting_agent_id: int | None,
    keywords: list[str],
    situation: str,
) -> dict:
    """REPLACE one existing row's keywords. Touches nothing else. No commit.

    DWB-667. THIS IS THE ONE OPERATION IN THIS MODULE THAT DESTROYS A VALUE,
    and the module above it argues at length that filling is not editing. The
    distinction that makes this allowed is narrow and it is the whole
    justification, so it is written down rather than left to the diff:

      `condensed` IS THE LESSON. Revising it after the fact is revising what you
      learned once you know how the story ended, and a second thought about a
      lesson is a new lesson with its own created_at. That argument is sound and
      this function does not weaken it: `condensed` is not a parameter here, the
      request schema forbids the key, and there is no assignment to it below.

      `keywords` ARE AN INDEX. They are the terms a later situation is matched
      against. They make no claim about the past, so correcting them is not
      revising history - it is repairing a pointer that never pointed anywhere.
      A lesson whose keywords cannot be reached is stored and unserved, which is
      the same outcome as not having written it. 288 live scars are in exactly
      that state.

    WHY THE FILL ROUTE COULD NOT DO THIS, which is worth stating because the
    ticket assumed it could: `fill_memory` refuses with `already_set` any field
    that already carries a value, and 285 of those 288 rows already carry
    keywords. Fill never reaches its ownership check on them. There was no path
    to re-keywording a single row before this function existed.

    OWNER-ONLY IS UNCHANGED AND IS NOT RELAXED HERE. There is deliberately no
    operator parameter, no admin header and no impersonation path. The five
    agents holding those rows write their own, which costs more to arrange and
    is the only version where the words are the author's. It also keeps the
    DWB-667 measurement honest: the frozen situation set is published, and an
    author re-keywording blind to it is the only arrangement in which the
    after-number measures recall rather than measuring whoever wrote both sides.

    THE REPLACEMENT GOES THROUGH THE SAME GATE AS A FRESH WRITE. There would be
    no point repairing 288 dead pointers through a route that could store a dead
    one, so `keyword_reachability` runs here exactly as it runs in
    `raw_memory.append_raw_memory` - same module, same predicate, same refusals.

    Raises MemoryFillError with codes:
      - memory_not_found      (404)
      - memory_not_on_agent   (400)
      - actor_required        (400)
      - not_owner             (403)
      - keywords_unchanged    (409)
    and `raw_memory.RawMemoryWriteError` for a blank list, and
    `keyword_reachability.KeywordUnreachable` for an unreachable one - both
    unchanged from the write gate, because the same rule was broken.
    """
    memory = _require_owned_memory(
        db, agent_id=agent_id, memory_id=memory_id, acting_agent_id=acting_agent_id
    )

    # Refusals BEFORE any assignment, so a request that is going to be refused
    # leaves the row untouched even in the session's identity map.
    _require_keywords(keywords)
    keyword_reachability.require_situation(situation)
    # DWB-669. Same gate as a fresh write: there would be no sense running a
    # cleanup through a route that could store the thing being cleaned up.
    keyword_reachability.require_subject_bearing_keywords(keywords)
    keyword_reachability.require_reachable_keywords(keywords, situation)

    previous = list(memory.keywords or []) or None
    if previous is not None and list(keywords) == previous:
        # A no-op answering 200 is the shape this lane keeps finding: a caller
        # reading a success cannot tell "I repaired this row" from "I sent the
        # same dead keywords back and nothing happened". Over a 288-row pass
        # that difference is the whole result.
        raise MemoryFillError(
            "keywords_unchanged",
            f"memory {memory_id} already carries exactly these keywords, so "
            "this request would change nothing while answering 200. If you "
            "meant to re-keyword it, send different terms; if you are walking a "
            "backfill, this row is already done and the count should say so.",
        )

    # THE ONLY TWO ASSIGNMENTS IN THIS FUNCTION. `condensed`, `body`, `tier`,
    # the moment-tags, both session ids, `fired_count` and `source_journal_id`
    # are not named anywhere below, which is the point and is asserted
    # structurally in the tests rather than left to review.
    memory.keywords = list(keywords)
    memory.situation = situation
    db.flush()

    return {
        "memory_id": memory.id,
        "agent_id": memory.agent_id,
        "previous_keywords": previous,
        "keywords": memory.keywords,
        "situation": memory.situation,
        # Echoed and NOT writable. A caller can see the lesson line survived
        # this call rather than trusting that it did.
        "condensed": memory.condensed,
        "tier": memory.tier.value,
        "created_at": memory.created_at,
        "fired_count": memory.fired_count,
        "created_session_id": memory.created_session_id,
        "last_reinforced_session_id": memory.last_reinforced_session_id,
    }
