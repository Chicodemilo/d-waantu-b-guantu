# Path: app/services/memory_transition.py
# File: memory_transition.py
# Created: 2026-09-30 (DWB-596)
# Purpose: Compute a project's memory-mode transition status from the open run header and the states of its memory_transitions rows. Read-only by construction: this module contains no write of any kind.
# Caller: app/routers/projects.py (GET /projects/{id}/memory-transition)
# Callees: app/models/memory_transition (MemoryTransitionRun, MemoryTransition, TERMINAL_STATES), app/models/agent (names for the per-agent breakdown), app/schemas/memory_transition
# Data In: db: Session, project_id: int
# Data Out: MemoryTransitionStatusRead
# Last Modified: 2026-09-30 (DWB-596)

"""The transition status, DERIVED on every read.

WHY THIS MODULE HAS NO WRITES, AND WHY THAT IS THE FEATURE. Miles: the status
must be programmatic, "not an llm going oh I should update the display". A rule
saying agents must not post status updates holds until the day it does not, and
it fails silently: a stale status still looks live, and nothing distinguishes it
from a fresh one. So there is nothing to post. No status column exists, no
endpoint accepts one, no request field carries one, and this module cannot
write even if someone asked it to. The capability is absent rather than
forbidden, and a test asserts that.

WHAT "DONE" MEANS, AND WHY IT IS BORROWED RATHER THAN REDEFINED. An entry is
done when its state is in TERMINAL_STATES, which is the cutover guard's own
vocabulary (app/models/memory_transition). Restating it here as a comparison,
or as a list of state names, would create a second definition that drifts: the
day someone adds a state, the guard would decide one way and this display the
other, and the display would be the one people believe.
"""

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.memory_transition import (
    TERMINAL_STATES,
    MemoryTransition,
    MemoryTransitionRun,
    TransitionRunState,
    TransitionState,
)
from app.schemas.memory_transition import (
    MemoryTransitionAgentRow,
    MemoryTransitionStatusRead,
    TransitionStatus,
)


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _open_run(db: Session, project_id: int) -> MemoryTransitionRun | None:
    """The project's open run, or None.

    ONLY THE OPEN RUN IS REPORTED. Completed and aborted runs are history and
    the database keeps them for the audit trail, but reporting the most recent
    run regardless of state would make a project that finished a transition
    last month indistinguishable from one mid-flight today, at exactly the
    moment an operator is asking which it is. At most one run is open per
    project, enforced by a unique constraint rather than by this query.
    """
    stmt: Select = (
        select(MemoryTransitionRun)
        .where(MemoryTransitionRun.project_id == project_id)
        .where(MemoryTransitionRun.state == TransitionRunState.open)
    )
    return db.scalars(stmt).first()


def get_transition_status(
    db: Session, project_id: int
) -> MemoryTransitionStatusRead:
    """Build the status for ``project_id``. Never writes."""
    run = _open_run(db, project_id)
    if run is None:
        # No open run. Distinguish "never transitioned" from "transitioned and
        # finished": both have no open run, and answering both the same way is
        # the empty-result-means-everything failure this ticket exists to
        # prevent. Costs one EXISTS query on an indexed column.
        ever = db.scalars(
            select(MemoryTransitionRun.id)
            .where(MemoryTransitionRun.project_id == project_id)
            .limit(1)
        ).first()
        return MemoryTransitionStatusRead(
            project_id=project_id,
            status=(
                TransitionStatus.idle if ever else TransitionStatus.not_started
            ),
        )

    header = {
        "project_id": project_id,
        "run_id": run.id,
        "state": run.state,
        "direction": run.direction,
        "started_at": _iso(run.started_at),
        "enumerated_at": _iso(run.enumerated_at),
        "completed_at": _iso(run.completed_at),
        "aborted_at": _iso(run.aborted_at),
    }

    if run.enumerated_at is None:
        # Reported as its own value rather than as zero-of-zero. A count cannot
        # distinguish "enumeration ran and found nothing" from "enumeration
        # never ran", and the second is a defect: this is the ambiguity the run
        # table was added to remove, so the status must not reintroduce it.
        return MemoryTransitionStatusRead(
            **header, status=TransitionStatus.not_enumerated
        )

    rows = list(
        db.scalars(
            select(MemoryTransition)
            .where(MemoryTransition.run_id == run.id)
            .order_by(MemoryTransition.agent_id.asc(), MemoryTransition.id.asc())
        ).all()
    )

    # Names for the per-agent breakdown (AC4), fetched in one query rather than
    # per row. A missing agent yields a null name instead of dropping the row:
    # an agent deleted mid-transition still owns entries, and hiding them would
    # make the totals disagree with the breakdown.
    agent_ids = {r.agent_id for r in rows}
    names: dict[int, str | None] = {}
    if agent_ids:
        names = {
            a_id: a_name
            for a_id, a_name in db.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
        }

    per_agent: dict[int, list[int]] = {}
    # Counted separately from `done` on purpose. See the schema comment: all
    # three are terminal and only one of them means the entry is in the new
    # store, so a display that reports only `done` cannot distinguish a
    # migration that worked from one that discarded everything.
    by_outcome = {
        TransitionState.written: 0,
        TransitionState.journaled: 0,
        TransitionState.skipped: 0,
    }
    for row in rows:
        totals = per_agent.setdefault(row.agent_id, [0, 0])
        totals[0] += 1
        if row.state in TERMINAL_STATES:
            totals[1] += 1
        if row.state in by_outcome:
            by_outcome[row.state] += 1

    agents = [
        MemoryTransitionAgentRow(
            agent_id=agent_id,
            agent_name=names.get(agent_id),
            entries_total=total,
            entries_done=done,
            done=total == done,
        )
        for agent_id, (total, done) in sorted(per_agent.items())
    ]

    entries_total = len(rows)
    entries_done = sum(a.entries_done for a in agents)

    # Complete means every entry is terminal, so the cutover may proceed. It
    # does NOT mean the transition is over: the run stays open until the
    # cutover lands. A project that enumerated and legitimately found nothing
    # has zero entries and is complete, which is correct and is the case the
    # not_enumerated branch above exists to keep separate from it.
    status = (
        TransitionStatus.complete
        if entries_done == entries_total
        else TransitionStatus.in_progress
    )

    return MemoryTransitionStatusRead(
        **header,
        status=status,
        entries_total=entries_total,
        entries_done=entries_done,
        entries_written=by_outcome[TransitionState.written],
        entries_journaled=by_outcome[TransitionState.journaled],
        entries_skipped=by_outcome[TransitionState.skipped],
        agents_total=len(agents),
        agents_done=sum(1 for a in agents if a.done),
        agents=agents,
    )
