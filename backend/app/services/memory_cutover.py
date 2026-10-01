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
# Last Modified: 2026-09-30 (DWB-594)

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

An entry reaches a terminal state by being WRITTEN, SKIPPED or JOURNALED. Only
the first two words of that sentence preserve anything: `written` puts it in the
new store and `journaled` puts it in the journal, but `skipped` means "decided
it should not travel" and preserves it NOWHERE. So a run whose entries were all
skipped is fully terminal with nothing kept, and cutting over would seal the
flat file (DWB-589) against an empty store - an agent that had memory, has none,
and cannot read the file that still holds it.

That is indistinguishable from a bug that skipped everything, and the whole lane
exists because a state indistinguishable from a bug reached production. So it
REFUSES. Not a hold step in the normal flow, which the TL ruled against: the
normal flow is untouched, and this fires only on a run that preserved nothing.

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

from sqlalchemy import select
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
# absent: it is the one terminal state that keeps nothing.
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
    total = _row_count(db, run)
    if total and not _preserved_count(db, run):
        raise CutoverRefused(
            f"Cutover refused for project {project.id}: transition run {run.id} "
            f"has {total} entries and every one was skipped, so nothing was "
            "written to the store and nothing was journaled. Completing here "
            "would seal the flat file against an empty store - the agent would "
            "have had memory, have none, and be unable to read the file that "
            "still holds it. If that is genuinely intended, abort the "
            "transition (which needs no confirmation) or perform the cutover "
            "explicitly; it will not happen by arithmetic."
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
    run.completed_at = datetime.now(timezone.utc)
    project.memory_mode = target
    db.flush()
    return target
