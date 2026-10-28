# Path: app/services/memory_scar_conclude.py
# File: memory_scar_conclude.py
# Created: 2026-09-30 (DWB-609)
# Purpose: Execute the fifth movement - a scar at rest (score 6) whose context
#          has CONCLUDED moves into the journal, preserving its original date
#          via DWB-605's created_at column, then the agent_memories row is
#          deleted. The consumer app/services/memory_scan.ContextLiveness
#          .finished has never had.
# Caller: app/services/memory_consolidate.consolidate_agent (DWB-609)
# Callees: app/models/agent_memory, app/services/memory_score (score(),
#          sessions_since_reinforced() - the pure functions, not
#          scored_memory() itself), app/services/memory_scan (scan_context,
#          SCAR_FAMILY), app/services/journal
# Data In: db Session, an optional agent_id scope
# Data Out: ConcludeOutcome - the JournalEntry list this pass created, plus
#           the nominated / unfinished counts that tell an idle pass from a
#           blocked one (DWB-707)
# Last Modified: 2026-10-28 (DWB-707: the pass returns ConcludeOutcome rather
#                than a bare list, so "nominated zero" and "nominated N, none
#                finished" stop rendering identically)
#                (DWB-609: created)
#                (DWB-706: conclude_dry_run sizes the lane read-only, taken
#                with the resting-score gate still in place)

"""The fifth movement, finally with a consumer.

FROM THE HUMAN MEMORY AUDIT, 2026-09-30 AND ITS DWB-609 ADDENDUM: of Miles's
five movements, four had a hand (DWB-606 both scar-to-core paths, DWB-607 the
WORKING floor, DWB-608 journal-to-core). The fifth - "a scar at 6 whose
context is finished moves into the journal" - got a SCAN
(`memory_scan.scan_context` can answer `ContextLiveness.finished`) and no
actor. Grepping the app for that outcome outside memory_scan.py itself found
zero consumers. This module is the consumer, filed under DWB-609 because that
is where the gap was found and the ticket history should show it rather than
a silent scope expansion of DWB-606/607.

A SIBLING FILE, NOT A SIBLING FUNCTION IN memory_evict.py, DELIBERATELY.
memory_evict.py is DWB-607's delivered file, scoped tightly to the
WORKING-floor movement in its own header. This movement shares its SHAPE
(journal-before-delete, same tags-and-provenance pattern, same
created_at-carries-forward contract) but not its TRIGGER (a SCAN result, not a
score/band computation) or its TIER (scar-family, not WORKING). Keeping it in
its own file means DWB-607's file still says exactly what DWB-607 built, and
this one says exactly what DWB-609 added - the same reasoning that kept this
whole lane's modules one-movement-per-file rather than one-grab-bag-file.

"AT REST (SCORE 6)", NOT EVERY SCAR-FAMILY ROW, MATCHING THE SPEC'S OWN WORDS.
Spec section 2: "Entries sitting at 6 get periodically re-examined against the
current context." A context's liveness does not depend on how recently the
scar fired - a context can conclude on day one as easily as after ninety
sessions - but the spec scopes WHEN the re-examination runs to resting
entries, not every entry on every pass. Scoping candidates to `score() == 6`
(the resting value for FIRING_TIERS, memory_score._CURVE) matches that
wording exactly rather than scanning everything on every consolidation pass.
A scar still climbing toward 6 is presumably still being actively reinforced
and is not what section 2 means by "sitting at 6".

A MISSING OR BLANK context_key IS HANDLED BY scan_context ITSELF, NOT HERE.
Per the DWB-604/611 sequencing ruling (Archie + Stan + Barry, 2026-09-30), a
scar with no context_key now means `still_active` (take no action), not
`cannot_die` and not `finished`. This module does not pre-filter on
context_key presence; it hands every resting scar-family row to
`scan_context` and acts only on `finished`, which already encodes that rule.

ORDERING WITH SCAR-TO-CORE PROMOTION IS THE CALLER'S JOB, NOT THIS MODULE'S.
A scar can independently qualify for `cannot_die` (promote to CORE,
DWB-606/memory_promote.maybe_promote_scar) and, in principle, reach a
`finished` context_key read a session later - but never both in the SAME
read, because `scan_context` returns exactly one `ContextLiveness` value per
call and `cannot_die` and `finished` are mutually exclusive outcomes of the
same branch (a context_key either resolves to a closed ticket/epic, in which
case it is `finished` if closed else `still_active`, or it resolves to
nothing at all, which is `cannot_die` - never both for one key). The real
ordering hazard is between THIS movement and `fired_count`-triggered
promotion: a scar can satisfy both `fired_count >= 3` (promote) and have a
context that happens to have JUST concluded (evict) on the same pass, and
promoting first removes it from scar-family before this module's query ever
sees it - which is the correct outcome per Miles's own reasoning (recurrence
while held is evidence the lesson is durable, which outranks "the specific
episode that produced it is now historical"). `memory_consolidate.py` is
responsible for running promotion before this module in one consolidation
pass; this module does not re-check tier after the fact, it trusts its own
query, taken at call time, to already reflect the caller's ordering.

created_at CARRIES THE ORIGINAL DATE FORWARD; entered_at DOES NOT NEED TO.
Identical reasoning to DWB-607's evict_working_memories: `journal.create_entry
(created_at=memory.created_at)` is DWB-605's contract, `entered_at` is left to
its own server_default (now()) because concluding IS when this entry
genuinely arrives in the journal, only the memory's own age must survive.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import journal as journal_svc
from app.services import memory_scan
from app.services import memory_score

# Tags every journal entry written by this movement carries, so a human
# reading the journal later can see why the entry arrived without joining
# back to an agent_memories row that no longer exists. Same precedent as
# memory_evict.EVICTION_TAGS, memory_revert.JOURNAL_TAGS_DROPPED and
# memory_decide.SKIP_TAGS.
CONCLUDED_TAGS = ["consolidation", "context-concluded"]

# The resting value for any FIRING_TIERS curve (memory_score._CURVE), spec
# section 3's "31-90" bucket and beyond. Not imported from memory_score
# because nothing there names it as a constant - it is read directly off the
# curve here, once, with the citation rather than a magic number repeated.
_RESTING_SCORE = 6


def _scars_at_rest(db: Session, *, agent_id: int | None) -> list[AgentMemory]:
    """Every scar-family row whose derived score is at the resting value.

    Mirrors memory_evict._working_memories_at_floor's shape exactly, for the
    sibling movement: same unscored-row exclusion (no session origin), same
    direct calls to the pure score functions rather than `scored_memory()` -
    see the module docstring on why going through that function is not an
    option here regardless of how its own firing question resolves.
    """
    conditions = [AgentMemory.tier.in_(memory_scan.SCAR_FAMILY)]
    if agent_id is not None:
        conditions.append(AgentMemory.agent_id == agent_id)

    memories = list(
        db.execute(select(AgentMemory).where(*conditions).order_by(AgentMemory.id.asc()))
        .scalars()
        .all()
    )

    at_rest = []
    for memory in memories:
        gap = memory_score.sessions_since_reinforced(db, memory)
        if gap is None:
            # Same exclusion scored_memory() applies: a row with no session
            # origin is reported unscored, never a candidate for anything.
            continue
        if memory_score.score(MemoryTier.scar, gap) == _RESTING_SCORE:
            at_rest.append(memory)
    return at_rest


@dataclass
class ConcludeDryRun:
    """What a conclude pass WOULD do if the resting-score gate were removed.

    DWB-706 step 1. Read-only: nothing here moves, journals or deletes a row.

    IT IS TAKEN WITH THE GATE STILL IN PLACE, ON PURPOSE. A counter that first
    runs in the same change that alters the behaviour cannot say what the
    behaviour used to be, so the before-reading has to exist before the
    change does. `at_rest_now` is that before-reading: what the gate nominates
    today, which is the number the gate's removal is measured against.

    THE TWO NUMBERS THAT MATTER ARE `candidates_if_gate_removed` AND
    `would_move`, AND THEIR BEING DIFFERENT IS THE WHOLE INSTRUMENT. Measured
    2026-10-28: 866 and 0. One number alone cannot distinguish "the gate is
    holding back a flood" from "the gate is holding back nothing", and those
    call for opposite decisions.

    `candidates_including_unscored` exists because removing the score gate
    raises a question the gate currently hides: `_scars_at_rest` ALSO drops
    rows whose `sessions_since_reinforced` is None, and that exclusion is
    there because a row with no origin has no score to compare. Once the
    comparison goes, the exclusion's reason goes with it - so the dry run
    reports both populations rather than resolving that silently. Today the
    difference is 4 rows.
    """

    scar_family: int = 0
    """Every scar-family row in scope. The denominator."""

    unscored_no_origin: int = 0
    """Rows with no session origin, so no derivable score."""

    at_rest_now: int = 0
    """THE BEFORE-READING: what the live gate nominates today."""

    candidates_if_gate_removed: int = 0
    """Rows that would be examined with the score comparison gone, keeping the
    unscored exclusion."""

    candidates_including_unscored: int = 0
    """As above, if the unscored exclusion went too. Reported, not chosen."""

    would_move: int = 0
    """Candidates whose context is `finished` - the rows that would actually
    be journaled and deleted. This is the number a human should read."""

    would_move_including_unscored: int = 0

    verdicts: dict = field(default_factory=dict)
    """scan_context outcome counts over the candidate set, by value."""

    scan_errors: int = 0
    """Rows whose scan raised. A NAMED THIRD STATE: not finished, not
    unfinished. Folding these into either would let a broken scan read as a
    clean verdict."""


def conclude_dry_run(
    db: Session, *, agent_id: int | None = None
) -> ConcludeDryRun:
    """Size the conclude lane without moving anything.

    Answers the question the ticket's acceptance asks for: what WOULD move if
    the resting-score precondition were removed. Pure read - no flush, no
    delete, no journal entry.

    Deliberately does NOT call `_scars_at_rest` for the counterfactual, because
    that function IS the gate. It re-derives the same population and applies
    only the exclusion that would survive, so the two numbers come from one
    traversal and cannot drift from each other the way two queries would.
    """
    conditions = [AgentMemory.tier.in_(memory_scan.SCAR_FAMILY)]
    if agent_id is not None:
        conditions.append(AgentMemory.agent_id == agent_id)

    memories = list(
        db.execute(select(AgentMemory).where(*conditions).order_by(AgentMemory.id.asc()))
        .scalars()
        .all()
    )

    out = ConcludeDryRun(scar_family=len(memories))
    verdicts: dict[str, int] = {}

    for memory in memories:
        gap = memory_score.sessions_since_reinforced(db, memory)
        scored = gap is not None
        if not scored:
            out.unscored_no_origin += 1
        elif memory_score.score(MemoryTier.scar, gap) == _RESTING_SCORE:
            out.at_rest_now += 1

        if scored:
            out.candidates_if_gate_removed += 1
        out.candidates_including_unscored += 1

        try:
            verdict = memory_scan.scan_context(db, memory)
        except Exception:
            # Never let one row's scan failure become a verdict about the lane.
            out.scan_errors += 1
            continue
        key = getattr(verdict, "value", str(verdict))
        verdicts[key] = verdicts.get(key, 0) + 1
        if verdict == memory_scan.ContextLiveness.finished:
            out.would_move_including_unscored += 1
            if scored:
                out.would_move += 1

    out.verdicts = verdicts
    return out


@dataclass
class ConcludeOutcome:
    """What one conclude pass DID and what it had to work with (DWB-707).

    THE EMPTY LIST WAS LOAD-BEARING AND AMBIGUOUS. Before this, the pass
    returned `list[JournalEntry]` and nothing else, so "no scar was nominated"
    and "scars were nominated and none had finished contexts" both arrived as
    `[]` and were logged identically as `concluded_scars: 0`. Fourteen
    consecutive passes reported that, every one of them with zero candidates,
    and the log could not have shown the difference if the second case had
    occurred.

    THAT DIFFERENCE IS ABOUT TO MATTER, WHICH IS WHY THIS EXISTS NOW. Measured
    2026-10-28: the resting score 6 IS reachable (`memory_score.score` returns
    6 at a gap of 31+ sessions) and the oldest scar in the store sits at a gap
    of 21. So the lane is roughly ten sessions from nominating its first-ever
    candidate, at which point it moves from the first case to the second - and
    without these counts that transition is invisible. `scan_context` returns
    `finished` for 0 of 868 rows today, so the second case will produce an
    empty `created` for some time after.

    `nominated` and `unfinished` are COUNTS, not lists. The rows themselves are
    already reachable through the store; what no caller could reconstruct after
    the fact is how many the pass considered, because nomination leaves no
    trace when it does not act.
    """

    created: list[JournalEntry] = field(default_factory=list)
    """Journal entries written by this pass. The pass's EFFECT."""

    nominated: int = 0
    """Scars that passed the score gate and were examined. Zero here means the
    pass could not have acted whatever the contexts said."""

    unfinished: int = 0
    """Nominated scars whose context was not `finished`, so they were skipped.
    `nominated - unfinished == len(created)` always holds."""


def evict_concluded_scars(
    db: Session, *, agent_id: int | None = None
) -> ConcludeOutcome:
    """Move every resting scar whose context has concluded into the journal,
    then delete the agent_memories row.

    DWB-707: returns a `ConcludeOutcome`, not a bare list. Callers that want
    the effect read `.created`; the two counts beside it are what let a reader
    tell an idle pass from a blocked one. See the dataclass for why that
    distinction stopped being hypothetical.

    `agent_id=None` scopes to every agent, matching
    `memory_evict.evict_working_memories` and
    `memory_promote.promote_journal_candidates`'s own defaults - the
    consolidation job runs this per session, not per agent.

    Idempotent by construction, same reasoning as evict_working_memories:
    once a scar is evicted its agent_memories row is gone, so a repeated call
    simply finds nothing left to nominate.
    """
    candidates = _scars_at_rest(db, agent_id=agent_id)
    if not candidates:
        # NOMINATED ZERO. Returned as a distinct fact rather than as an empty
        # list, because the caller cannot otherwise tell this from a pass that
        # examined candidates and found none finished.
        return ConcludeOutcome()

    created: list[JournalEntry] = []
    unfinished = 0
    for memory in candidates:
        if memory_scan.scan_context(db, memory) != memory_scan.ContextLiveness.finished:
            unfinished += 1
            continue
        entry = journal_svc.create_entry(
            db,
            agent_id=memory.agent_id,
            body=memory.body,
            tags=list(CONCLUDED_TAGS),
            created_at=memory.created_at,
        )
        # Flushed BEFORE the delete, per hard rule 4: a failure here leaves
        # the memory intact and the journal merely early, never the reverse.
        db.flush()
        db.delete(memory)
        created.append(entry)

    db.flush()
    return ConcludeOutcome(
        created=created, nominated=len(candidates), unfinished=unfinished
    )
