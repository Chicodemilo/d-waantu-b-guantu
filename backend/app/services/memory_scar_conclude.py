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
#                (DWB-706: conclude_dry_run sizes the lane read-only; step 2
#                removed the resting-score gate - _scars_at_rest is now
#                _conclude_candidates and nominates every scar in scope)

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

WITHDRAWN 2026-10-28 BY DWB-706, KEPT IN PLACE BECAUSE THE ARGUMENT STILL
READS AS SOUND. This module used to open by defending a score==6 precondition:
spec section 2 says "entries sitting at 6 get periodically re-examined against
the current context", so candidates were scoped to the resting value rather
than scanned every pass, on the reasoning that a scar still climbing toward 6
is being actively reinforced.

WHAT KILLED IT IS IN THE SAME PARAGRAPH, AND IT WAS THERE ALL ALONG: "a
context's liveness does not depend on how recently the scar fired". That is
true, and the gate contradicted it. `sessions_since_reinforced` counts from
COALESCE(last_reinforced, created), so ANY recall resets the clock and a scar
that keeps being useful never arrives at 6 at all - measured 2026-10-28, zero
of 870 rows were at the resting score and the lane had never concluded
anything in its existence. The gate measured DISUSE, not whether the work
finished.

There is no clock condition now. `_conclude_candidates` returns every
scar-family row in scope and `scan_context` returning `finished` is the only
thing that concludes one. `_RESTING_SCORE` survives at line 115 for
`ConcludeDryRun.at_rest_now`, which gates nothing and is kept as a
measurement.

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


def _conclude_candidates(db: Session, *, agent_id: int | None) -> list[AgentMemory]:
    """Every scar-family row in scope. No clock condition of any kind.

    WAS `_scars_at_rest`, WHICH KEPT ONLY ROWS AT SCORE 6 (DWB-706). Renamed
    rather than left alone, because a function still called "at rest" that
    returns everything is a name a reader trusts and cannot see is wrong.

    WHY THE SCORE GATE WENT. A context question should not wait for a clock. A
    scar whose ticket closed yesterday is concluded whether or not enough
    sessions have passed to decay it. Measured before removal: 0 of 870
    scar-family rows were at the resting score, the largest gap in the store
    was 23 and score 6 first occurs at gap 31, so the context check had never
    run on anything - and `sessions_since_reinforced` counts from
    COALESCE(last_reinforced, created), so ANY recall resets the gap to zero.
    A row that fires on its way up never arrives at 6 at all. The gate was
    therefore not a delay, it was a condition on DISUSE, and disuse is not
    what "this work finished" means.

    WHY THE UNSCORED EXCLUSION WENT WITH IT, ruled by Archie_DWB. `gap is
    None` is a CLOCK FACT - it says the row has no session origin to count
    from. Keeping it inside a decision the clock was just removed from would
    smuggle the decay dependency back in through a side door, which is the
    same shape as the thing being removed wearing a different name. A row with
    no session origin can still have a context, and `scan_context` can still
    answer it; nothing about a missing clock origin makes "this work finished"
    less true. Measured at the time of the ruling: 4 rows sat in that
    difference.

    WHAT STILL STOPS A ROW BEING CONCLUDED is `scan_context` returning
    `finished`, and nothing else. The protection against concluding a lesson
    too early lives at the WRITE: DWB-704 refuses a key naming an
    already-closed ticket, and `context_free` lets an author declare that no
    single piece of work owns the lesson. A second condition here would
    rebuild what this removed.
    """
    conditions = [AgentMemory.tier.in_(memory_scan.SCAR_FAMILY)]
    if agent_id is not None:
        conditions.append(AgentMemory.agent_id == agent_id)

    return list(
        db.execute(select(AgentMemory).where(*conditions).order_by(AgentMemory.id.asc()))
        .scalars()
        .all()
    )


@dataclass
class ConcludeDryRun:
    """What a conclude pass WOULD do if the resting-score gate were removed.

    DWB-706 step 1. Read-only: nothing here moves, journals or deletes a row.

    IT WAS FIRST TAKEN WITH THE GATE STILL IN PLACE, ON PURPOSE. A counter
    whose first run is in the same change that alters the behaviour cannot say
    what the behaviour used to be, so the before-reading shipped one commit
    earlier (aa86d0a): 866 scored candidates, 870 including unscored, 0 moving.

    THE PAIR IS THE INSTRUMENT, NOT EITHER NUMBER. `candidates` and
    `would_move` being DIFFERENT is the whole point: one number alone cannot
    distinguish "the lane is holding back a flood" from "the lane is holding
    back nothing", and those call for opposite decisions.

    THE SCORED-ONLY PAIR IS KEPT AFTER THE CHANGE, DELIBERATELY. Archie_DWB
    ruled the unscored rows IN, so `candidates` is now the live population and
    `candidates_excluding_unscored` is the counterfactual. It stays so a future
    reader can see what that decision costs - the difference was 4 rows when
    it was made and will not stay 4.
    """

    scar_family: int = 0
    """Every scar-family row in scope. The denominator."""

    unscored_no_origin: int = 0
    """Rows with no session origin, so no derivable score. Since DWB-706 these
    are CANDIDATES like any other: a missing clock origin says nothing about
    whether the work finished."""

    at_rest_now: int = 0
    """Rows sitting at the resting score.

    GATES NOTHING SINCE DWB-706 and is kept only as a measurement. It was the
    before-reading while the score gate existed; reading it as "what the pass
    will nominate" is now wrong, which is why it no longer says that."""

    candidates: int = 0
    """THE LIVE POPULATION: every scar-family row the pass examines."""

    candidates_excluding_unscored: int = 0
    """The counterfactual - what the population would be if rows with no
    session origin were still excluded. Reported, not used."""

    would_move: int = 0
    """Live candidates whose context is `finished`, i.e. the rows that will
    actually be journaled and deleted. This is the number a human should
    read."""

    would_move_excluding_unscored: int = 0

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

    Re-derives the population in ONE traversal rather than calling
    `_conclude_candidates` and counting separately, so the live counts and the
    counterfactual cannot drift from each other the way two queries would.
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
            out.candidates_excluding_unscored += 1
        out.candidates += 1

        try:
            verdict = memory_scan.scan_context(db, memory)
        except Exception:
            # Never let one row's scan failure become a verdict about the lane.
            out.scan_errors += 1
            continue
        key = getattr(verdict, "value", str(verdict))
        verdicts[key] = verdicts.get(key, 0) + 1
        if verdict == memory_scan.ContextLiveness.finished:
            out.would_move += 1
            if scored:
                out.would_move_excluding_unscored += 1

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
    """Move every scar whose context has concluded into the journal,
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
    candidates = _conclude_candidates(db, agent_id=agent_id)
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
