# Path: app/services/memory_sweep.py
# File: memory_sweep.py
# Created: 2026-09-30 (DWB-594)
# Purpose: The SWEEP phase - pick up anything written to a memory file since
#          the snapshot and add it to the open run as new pending rows.
# Caller: DWB-594's decide/sweep endpoint, and the cutover path before landing
# Callees: app/services/memory_adopt (the shared enumerator)
# Data In: db Session, Project, MemoryTransitionRun
# Data Out: SweepResult (what was added, and whether it came back empty)
# Last Modified: 2026-09-30 (DWB-594)

"""Phase 4: catch what was written while the judging was happening.

DWB-594 phase 4, verbatim: "Anything appended since the snapshot becomes new
`pending` rows. Repeat until the sweep comes back empty. Memory keeps being
written during the judgment loop, which is exactly why the loop cannot be the
freeze."

That last clause is the design. The judgement loop is long - one question per
entry, across every agent - and freezing memory writes for its duration would
stop the team working. So writes continue, and the sweep is what makes that
safe.

THE DIFF IS A MULTISET, NOT A SET, and that is the non-obvious part.

Comparing distinct excerpts would silently swallow a genuine duplicate: an agent
that writes the same lesson twice has two entries in its file, and a set
difference would enumerate one and drop the other forever. So the comparison is
by COUNT per excerpt - the file has three copies and the run has one row, so two
are added. A duplicate is a candidate like any other, and the decide phase is
where someone judges it a duplicate and skips it, which is the phase that is
supposed to make that call.

ROWS ARE NEVER REMOVED, only added. An agent that CONDENSES mid-run rewrites its
file, so excerpts the snapshot captured can vanish from it. Those rows stay: they
record a judgement that was made, or a question that was asked, and deleting
them would make the audit trail a lie. The condensed replacements arrive as new
candidates, which is the honest outcome - the agent rewrote the lesson, so it
gets asked about the rewrite.

TERMINAL ROWS COUNT AS ALREADY ENUMERATED. The comparison is against every row
in the run, not just the pending ones, or every sweep would re-add everything
already decided and the loop would never come back empty.
"""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionState,
)
from app.models.project import Project
from app.services import memory_adopt


@dataclass
class SweepResult:
    """What one sweep found.

    `is_empty` is the loop's termination condition, and it is a property of what
    was ADDED rather than of what exists: a sweep that adds nothing is the
    signal that the file has stopped moving, regardless of how many rows are
    still waiting to be decided.
    """

    added: list[MemoryTransition] = field(default_factory=list)
    # Carried through from the enumerator so a sweep cannot quietly succeed
    # against a file it could not read. Same reason the snapshot surfaces it:
    # unreadable and empty look identical downstream and only one is safe.
    unreadable: list[str] = field(default_factory=list)
    content_without_candidates: list[str] = field(default_factory=list)

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def is_empty(self) -> bool:
        return not self.added

    @property
    def is_defective(self) -> bool:
        return bool(self.unreadable or self.content_without_candidates)


def _existing_excerpts(db: Session, run: MemoryTransitionRun) -> Counter:
    """Every excerpt already enumerated for this run, counted per agent.

    Keyed by (agent_id, excerpt) rather than by excerpt alone: two agents can
    legitimately hold the same lesson, and collapsing them would leave the
    second agent's copy unenumerated forever.
    """
    rows = db.execute(
        select(MemoryTransition.agent_id, MemoryTransition.source_excerpt).where(
            MemoryTransition.run_id == run.id
        )
    ).all()
    return Counter((agent_id, excerpt) for agent_id, excerpt in rows)


def sweep(
    db: Session, project: Project, run: MemoryTransitionRun, *, persist: bool = True
) -> SweepResult:
    """Add rows for anything in the files that the run has not enumerated yet.

    Returns a SweepResult whose `is_empty` is the termination condition: repeat
    until a sweep adds nothing, and only then cut over.

    `persist=False` is the dry run and writes nothing, same contract as the
    snapshot.

    Does NOT commit, and does NOT touch the run's state or `enumerated_at` -
    those belong to DWB-593's edges, and a sweep is not a new enumeration, it is
    the same one catching up.
    """
    result = SweepResult()

    # Re-enumerate from scratch WITHOUT persisting, then diff. Reusing the
    # snapshot's enumerator rather than writing a second walker is the whole
    # point: two implementations of "what are the candidates" would drift, and
    # the drift would show up as entries the sweep never catches.
    fresh = memory_adopt.enumerate_candidates(db, project, run, persist=False)
    result.unreadable = list(fresh.unreadable)
    result.content_without_candidates = list(fresh.content_without_candidates)

    already = _existing_excerpts(db, run)

    for row in fresh.rows:
        key = (row.agent_id, row.source_excerpt)
        if already[key] > 0:
            # Already enumerated in this run, in whatever state. Decrement so a
            # genuine duplicate in the file still gets its own row: the file has
            # N copies and the run has M, so N - M are added.
            already[key] -= 1
            continue
        result.added.append(row)
        if persist:
            db.add(row)

    if persist and result.added:
        db.flush()

    return result
