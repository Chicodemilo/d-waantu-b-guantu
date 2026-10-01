# Path: app/services/memory_cutover.py
# File: memory_cutover.py
# Created: 2026-09-30 (DWB-594)
# Purpose: Automatic cutover - when the last transition row reaches a terminal
#          state the run completes and the project lands on the far side. Both
#          directions. Never fires without proof that enumeration happened.
# Caller: app/services/* (DWB-594's decide path, after a row goes terminal)
# Callees: app/services/project (open_run, the legal-edge table), app/models
# Data In: db Session, Project
# Data Out: the MemoryMode landed in, or None when the run is not finished
# Last Modified: 2026-10-01 (DWB-634: _completion_now delegates to the shared
#                app.services.timestamps helper, same expression, one owner;
#                previous entry: DWB-622 the refusal reports measured state
#                counts instead of asserting nothing was journaled; the
#                preserving set is unchanged and now carries why)

"""Cutover is the pipeline finishing, not a thing someone does afterwards.

TL ruling, 2026-09-30: the cutover fires AUTOMATICALLY when the last transition
row reaches a terminal state. There is no control for it and no hold step.

THREE REASONS, AND THE SECOND DECIDES IT:

1. The design's own sentence - a transition is a pipeline that ENDS in a mode
   change. The mode change IS the pipeline finishing.
2. Miles's constraint. If cutover needs someone to decide it has happened, that
   someone is an agent, and the transition must not depend on an agent choosing
   to do housekeeping. Same logic that put enumeration inside the BEGIN edge.
3. There is nothing left to review. Every entry was decided individually on the
   way through, so a review step at the end re-asks questions already answered,
   with no information the operator lacked at each decision. The DRY RUN serves
   the see-it-before-it-happens case, at the useful moment: before the work
   rather than after all of it.

WHY THIS ASSERTS `enumerated_at` AND NOT MERELY "NO ROWS IN FLIGHT". That is the
bug that caused this whole rework. A guard asking only whether any row is
unfinished passes TRIVIALLY when there are no rows, so `stock -> adopting ->
human_memory` walked straight into an empty store in two calls - the original
amnesia bug, through the machine built to prevent it.

Zero rows after a real enumeration and zero rows because nothing ran are
different facts, and no count can tell them apart. `run.enumerated_at` can, and
it is the precondition here rather than a nice-to-have: without it this module
is the same defective guard with a new name.

ALL-TERMINAL IS NOT THE SAME AS ANYTHING-SURVIVED, and that gap is the third
door into the same bug. Found by Barry rather than by me.

An entry reaches a terminal state by being WRITTEN, SKIPPED or JOURNALED, and
the question the guard asks is whether the entry still exists ANYWHERE
afterwards. A run that enumerated candidates and preserved none of them is
about to seal the flat file (DWB-589) against an empty store - an agent that
had memory, has none, and cannot read the file that still holds it. That is
indistinguishable from a bug that discarded everything, and the whole lane
exists because a state indistinguishable from a bug reached production. So it
REFUSES. Not a hold step in the normal flow, which the TL ruled against: the
normal flow is untouched, and this fires only on a run that preserved nothing.

DWB-622 CORRECTION, AND IT IS A CORRECTION OF THIS PARAGRAPH. The original
version said `skipped` "preserves it NOWHERE", and excluded it from the
preserving set on that basis. The sentence was false: DWB-594's own ruling
makes every skip journal the entry FIRST, flushed before the row goes terminal,
so a terminal `skipped` row on an OPEN run implies a journal row. Nothing
caught it because the claim and the code agreed with each other while both
disagreed with `skip()`.

THE SET ITSELF WAS RIGHT AND STAYS UNCHANGED. Only the sentence explaining it
was false, and only the refusal's MESSAGE was broken. `{written, journaled}` is
a union across BOTH DIRECTIONS - `written` is how an adopt reaches its
destination, `journaled` is how a revert reaches its. Two edits were tried here
before that became clear, and both were wrong in instructive ways: adding
`skipped` lets an all-skipped run seal the file against an empty store, and
narrowing to `{written}` refuses every legitimate revert. The second is the
sharper warning, because it reads as rigour while breaking the case it was
cheapest to support.

So the defect was never that the refusal fired. It was WHAT IT SAID: an
all-skipped run was told nothing had been journaled, in exactly the case where
everything had been. An operator who checks that claim finds six journal rows
and has been given a reason to distrust the entire refusal, which is worse than
a wrong number.

SCOPE, because `skipped` has a second writer. The abort path
(`project.py`) marks rows skipped WITHOUT journaling, so there the implication
does not hold. It cannot reach here: that same transaction sets the run to
`aborted`, and this function resolves its run through `open_run`, which matches
only `state == open`. The status service reports only the open run for the same
reason. A test pins that.

The escape is deliberate rather than absent. `adopting -> stock` is an abort and
needs no confirmation, and the explicit CUTOVER edge remains reachable by PATCH
for an operator who genuinely means it. So the project is never trapped; it just
cannot arrive at an empty store by arithmetic alone.

A FINAL SWEEP RUNS BEFORE THE FLIP, AND THE CUTOVER IS ABANDONED IF IT FINDS
ANYTHING. DWB-594 acceptance 4: "Cutover happens only after a sweep returns
empty." Without it, a lesson written between the last decision and the flip is
enumerated by nobody and sealed away unread - the judgement loop is long and
memory keeps being written throughout, which is the whole reason the loop is not
the freeze.

ON THE FREEZE, PLAINLY, BECAUSE THE TICKET SANCTIONS A FALLBACK AND I TOOK PART
OF IT. The ticket asks for a bounded memory-write freeze covering the final
sweep and the flip. There is NO LOCK here. What there is: the final sweep and
the flip happen in one transaction, so no OTHER request can interleave a
transition step between them.

What that does not cover is a direct write to the memory FILE landing between
the sweep's read and the commit. That window is milliseconds and the loss is
recoverable - the file still exists on disk untouched, and a revert unseals it -
but it is a real window and I am naming it rather than implying a freeze I did
not build.

IT DOES NOT BYPASS THE LEGAL-EDGE TABLE. The flip it performs is the CUTOVER
edge that table already defines, looked up rather than assumed, so
`stock -> human_memory` stays absent from every path including this one.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.memory_transition import (
    TERMINAL_STATES,
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import timestamps

# Where each direction lands when its pipeline finishes. Data rather than an
# if/else so a direction added later has to state its destination instead of
# falling through to a default, which is the same reason DWB-593's edge table is
# a dict.
_LANDING: dict[TransitionDirection, MemoryMode] = {
    TransitionDirection.adopt: MemoryMode.human_memory,
    TransitionDirection.revert: MemoryMode.stock,
}


class CutoverRefused(Exception):
    """Raised when a cutover was attempted that must not proceed.

    Only one case reaches this today: a run whose enumeration never ran. It is
    an exception rather than a quiet `None` because `None` already means "not
    finished yet", which is an ordinary, expected answer. Folding a broken
    precondition into the same value as a normal negative is how the original
    guard came to pass trivially.
    """


def _completion_now() -> datetime:
    """Now, TRUNCATED to the second. Same reason as
    `memory_decide._decision_now()`; see DWB-633.

    MySQL ROUNDS a value carrying a fraction HALF-UP into a DATETIME(0) column
    rather than truncating it, so an unrounded stamp records a completion up to
    half a second after it happened - a timestamp naming a moment that has not
    occurred.

    THE FRACTION IS THE PROBLEM, NOT THE WRITER. Do not replace this with a
    server-side default on the assumption that MySQL-generated values truncate:
    `CAST(NOW(3) AS DATETIME)` rounds up just as a Python stamp does. Plain
    `NOW()` is safe only because it is GENERATED at second precision, so no
    fraction ever exists. A substitute is acceptable only if it has that same
    property.
    """
    return timestamps.aware_utc_now_second()


def _unfinished_count(db: Session, run: MemoryTransitionRun) -> int:
    return len(
        db.execute(
            select(MemoryTransition.id)
            .where(MemoryTransition.run_id == run.id)
            .where(MemoryTransition.state.notin_(list(TERMINAL_STATES)))
        )
        .scalars()
        .all()
    )


# Terminal states that PRESERVE the entry somewhere. `skipped` is deliberately
# absent.
#
# DWB-622 LEFT THIS SET EXACTLY AS IT WAS, and the reason is worth recording
# because two different wrong changes were attempted here first.
#
# The comment that used to sit on this set said `skipped` "keeps nothing". That
# sentence is false: DWB-594 makes every skip journal the entry before the row
# goes terminal. But the SET was still right, and the defect was only ever the
# refusal's MESSAGE, which asserted that nothing had been journaled in exactly
# the case where everything had.
#
# Wrong change 1: add `skipped`. That makes an all-skipped run cut over, which
# seals the flat file against an empty store - the precise harm this guard
# exists to refuse, since the journal is never auto-loaded.
#
# Wrong change 2: narrow to `{written}` on the reasoning that only the store
# counts. That reasoning holds for ADOPT and breaks REVERT, whose entries land
# as `journaled` rather than `written`. The set is a union across BOTH
# directions: `written` is how an adopt succeeds, `journaled` is how a revert
# does. Narrowing it made the guard refuse every legitimate revert, which is
# the classic shape - tightening a predicate until it also refuses the case it
# was cheapest to support.
#
# So the question this set answers is "did the entry reach its destination for
# this run's direction", and the union is what makes one set serve both.
_PRESERVING_STATES = frozenset(
    {TransitionState.written, TransitionState.journaled}
)


def _preserved_count(db: Session, run: MemoryTransitionRun) -> int:
    return len(
        db.execute(
            select(MemoryTransition.id)
            .where(MemoryTransition.run_id == run.id)
            .where(MemoryTransition.state.in_(list(_PRESERVING_STATES)))
        )
        .scalars()
        .all()
    )


def _state_counts(db: Session, run: MemoryTransitionRun) -> dict[str, int]:
    """What the run's rows actually are, for the refusal to REPORT rather than
    assert. DWB-622: the previous message hard-coded "every one was skipped ...
    nothing was journaled", which was a claim about the data instead of a
    reading of it, and it was false for every all-skipped run."""
    counts: dict[str, int] = {}
    for state, count in db.execute(
        select(MemoryTransition.state, func.count(MemoryTransition.id))
        .where(MemoryTransition.run_id == run.id)
        .group_by(MemoryTransition.state)
    ).all():
        counts[state.value if hasattr(state, "value") else str(state)] = count
    return counts


def _row_count(db: Session, run: MemoryTransitionRun) -> int:
    return len(
        db.execute(
            select(MemoryTransition.id).where(MemoryTransition.run_id == run.id)
        )
        .scalars()
        .all()
    )


def complete_if_finished(db: Session, project: Project) -> MemoryMode | None:
    """Land the project on the far side if its transition is done.

    Returns the mode landed in, or None when there is nothing to do - no open
    run, or rows still in flight. Both of those are ordinary answers and the
    caller is expected to ignore them.

    Call it after ANY row reaches a terminal state. It is idempotent and cheap:
    a second call against a completed run finds no open run and returns None.

    Raises CutoverRefused when the open run has no `enumerated_at`. That state
    is unreachable through DWB-593's BEGIN edge, which enumerates atomically,
    but it is reachable by anything else that creates a run - a repair script, a
    fixture, a direction added later. A guard that is unreachable through one
    door is not unreachable.

    Does NOT commit. The caller owns the transaction, as everywhere else in this
    lane, so a cutover and the decision that triggered it land together or not
    at all.
    """
    # Imported lazily: app/services/project.py imports this lane's modules from
    # inside its functions for the same reason, and a module-level import in
    # both directions is a cycle.
    from app.services.project import LEGAL_MEMORY_MODE_EDGES, CUTOVER, open_run

    run = open_run(db, project.id)
    if run is None:
        return None

    if run.enumerated_at is None:
        raise CutoverRefused(
            f"Cutover refused for project {project.id}: transition run {run.id} "
            "has no enumerated_at, so there is no evidence enumeration ever ran. "
            "Zero rows after a real enumeration and zero rows because nothing "
            "ran are different facts and a count cannot tell them apart. "
            "Completing here would land the project on the far side against a "
            "store that was never filled, which is the bug this lane exists to "
            "close."
        )

    if _unfinished_count(db, run):
        return None

    # ALL TERMINAL IS NOT ALL SURVIVED. A run that enumerated candidates and
    # preserved none of them is about to seal the flat file against an empty
    # store, which is the bug this lane exists to close wearing a third face.
    # Zero candidates is a different and legitimate case, handled at BEGIN, so
    # it is excluded here rather than swept into the same refusal.
    #
    # DWB-622: the message no longer asserts what the entries were or where
    # they did not go. It REPORTS the state counts it measured. The previous
    # text hard-coded "every one was skipped ... nothing was journaled", which
    # was a claim about the data rather than a reading of it, and it was false
    # for every all-skipped run because skips journal. An operator told
    # "nothing was journaled" while six journal rows sat there has been given a
    # reason to distrust the whole refusal.
    total = _row_count(db, run)
    if total and not _preserved_count(db, run):
        counts = _state_counts(db, run)
        breakdown = ", ".join(f"{state}: {n}" for state, n in sorted(counts.items()))
        raise CutoverRefused(
            f"Cutover refused for project {project.id}: transition run {run.id} "
            f"has {total} entries and not one of them reached its destination. "
            f"Entries by state - {breakdown}. Skipped entries ARE journaled "
            "and are not lost, but the journal is never auto-loaded, so "
            "completing here would seal the "
            "flat file against an empty store - the agent would have had "
            "memory, have none, and be unable to read the file that still "
            "holds it. If that is genuinely intended, abort the transition "
            "(which needs no confirmation) or perform the cutover explicitly; "
            "it will not happen by arithmetic."
        )

    # DWB-594 acceptance 4: a FINAL SWEEP, and no cutover if it finds anything.
    # Runs after the all-terminal check, so it only costs a file read on the
    # decision that would otherwise land. Anything it adds is non-terminal by
    # construction, so the run is no longer finished and the next decision will
    # re-check.
    from app.services import memory_sweep

    final = memory_sweep.sweep(db, project, run)
    if not final.is_empty:
        return None
    if final.is_defective:
        raise CutoverRefused(
            f"Cutover refused for project {project.id}: the final sweep could "
            "not read every memory file, so it cannot prove nothing arrived "
            f"late. Unreadable: {final.unreadable}; produced no candidates "
            f"despite having content: {final.content_without_candidates}. "
            "Sealing here could bury a lesson written during the transition."
        )

    target = _LANDING[run.direction]
    # Looked up, not assumed. The flip below must be an edge the table already
    # permits, so no path - including this one - can reach a mode the table
    # deliberately excludes.
    if LEGAL_MEMORY_MODE_EDGES.get((project.memory_mode, target)) != CUTOVER:
        raise CutoverRefused(
            f"Cutover refused for project {project.id}: "
            f"{project.memory_mode.value} -> {target.value} is not a cutover "
            "edge. The run's direction and the project's mode disagree, which "
            "means something moved the mode outside the state machine."
        )

    run.state = TransitionRunState.completed
    run.completed_at = _completion_now()
    project.memory_mode = target
    db.flush()
    return target
