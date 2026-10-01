# Path: app/services/memory_transition.py
# File: memory_transition.py
# Created: 2026-09-30 (DWB-596)
# Purpose: Compute a project's memory-mode transition status from the open run header and the states of its memory_transitions rows. Read-only by construction: this module contains no write of any kind.
# Caller: app/routers/projects.py (GET /projects/{id}/memory-transition)
# Callees: app/models/memory_transition (MemoryTransitionRun, MemoryTransition, TERMINAL_STATES), app/models/agent (names for the per-agent breakdown), app/schemas/memory_transition
# Data In: db: Session, project_id: int
# Data Out: MemoryTransitionStatusRead
# Last Modified: 2026-10-01 (DWB-622 entries_journaled overlay; DWB-623 re-enqueue detection)

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

from datetime import datetime, timezone

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


# States whose content reached the journal. `skipped` is here because
# memory_decide.skip() writes the journal entry and FLUSHES it before moving the
# row terminal, so a terminal skipped row implies a journal row. `journaled` is
# kept because the state still exists and a legacy row could carry it, not
# because anything in app/ writes it - nothing does, which is the defect
# DWB-622 fixed.
_JOURNALED_STATES = frozenset(
    {TransitionState.skipped, TransitionState.journaled}
)


def _re_enqueued_agents(rows: list[MemoryTransition]) -> set[int]:
    """Agents that had finished everything they held and have work again.

    DWB-623. Derived from columns that already exist, in keeping with this
    module writing nothing: no history table, no flag anyone has to remember to
    set, and therefore nothing that can go stale while still looking live.

    THE PREDICATE, AND WHY IT IS THIS ONE. An agent counts as re-enqueued when
    all three hold:

      1. it has at least one DECIDED row - so it genuinely started;
      2. it has at least one non-terminal row now - so it is holding work;
      3. EVERY one of those non-terminal rows was created AFTER that agent's
         most recent decision.

    Condition 3 is what makes this a statement about RECESSION rather than
    about mere incompleteness, and it is the one a looser version gets wrong.
    An agent still working through its original queue has non-terminal rows
    that predate its last decision, so it fails 3 and is correctly not
    reported. An agent whose queue drained and whose own wrap-up write came
    back round as a fresh candidate has nothing left from the original
    enumeration, so every remaining row postdates its last decision and it is
    reported.

    The safe case and the dangerous case answer this differently, which is the
    property a count of unfinished rows does not have: "has non-terminal rows"
    is equally true of an agent that never started, an agent mid-queue, and an
    agent that drained and re-enqueued, and those three want different
    responses from whoever is watching.

    CONSERVATIVE BY CONSTRUCTION. Without stored history there is no way to
    prove the agent was ever simultaneously at zero, so this can under-report:
    an agent that re-enqueues while still holding original rows is not flagged.
    It cannot over-report, which is the direction that matters - a detector
    that cries wolf gets ignored and then removed, and this one exists to be
    believed the fourth time it fires.

    THE CLOCK LIMIT, STATED RATHER THAN DISCOVERED LATER, AND IT IS WORSE THAN
    RESOLUTION. Both columns are MySQL `datetime` with no fractional seconds,
    so same-second events are indistinguishable. But the two sides do not even
    ROUND the same way, which makes the error up to a full second rather than
    half of one:

      `created_at`  MySQL's own NOW() into DATETIME(0)       TRUNCATES
      `decided_at`  a Python datetime carrying microseconds  ROUNDS half-up

    Measured here: a decision at wall 18:17:24.635 stored as 18:17:25, and a
    row genuinely created after it, at 18:17:24.6, stored as 18:17:24. The
    decision is recorded HALF A SECOND IN THE FUTURE and the later row looks
    earlier. So `created_at > decided_at` can be false for a row that really
    did arrive afterwards, and whether it is false depends on where in its
    second each event happened to fall - which is why a test driving the whole
    sequence in one burst is flaky rather than reliably red.

    FIXED AT SOURCE rather than compensated for here. The asymmetry was a
    latent defect wider than this function - any code ordering these two
    columns inherited it, and a decision stamped in the future is wrong
    independently of what reads it. `memory_decide._decision_now()` now
    truncates to the second, so both writers agree and the error is back down
    to the column's own one-second resolution.

    It was fixed there and not here deliberately. A tolerance in this predicate
    would have made the recession detector pass while leaving every other
    reader of those columns holding the same wrong ordering, and it would have
    blunted exactly the comparison this function depends on.

    For THIS predicate the asymmetry is harmless, because it can only ever
    cause an under-report and production gaps are minutes: the sweep that finds
    a wrap-up runs when some OTHER agent finishes. Do not paper over it with a
    one-second tolerance. A `>=`, or any slack, would make the equal-second
    case flag, and that case includes an agent merely part-way through its
    original queue, which is the exact confusion this predicate exists to
    avoid.

    ONE CASE IS STRUCTURALLY UNDETECTABLE HERE, AND IT IS NOT A BUG. The sweep
    runs INSIDE `decide_and_maybe_cut_over`, so for the agent whose own final
    decision triggers it, the new row's `created_at` and that agent's last
    `decided_at` are the same instant by construction - not merely the same
    second. That agent can never satisfy condition 3 and will never be flagged,
    however precise the clock becomes. Every OTHER agent that drained earlier
    is flagged normally, and that is the population this exists for: tonight's
    recessions were agents who had gone quiet and whose writes were found by
    somebody else's decision.

    Do not widen the predicate to catch it. The information is not lost, it is
    carried by a different field: that agent's `done` is False and its
    `entries_total` has grown, both visible in the same response. A detector
    that misses a case another field already covers is sound; one that
    over-reports trains people to ignore it, and then it gets removed.

    NO `.add()` ANYWHERE IN THIS MODULE, DELIBERATELY. DWB-596's guard forbids
    this file from calling commit/add/add_all/flush/delete/merge, by NAME, so
    that the read path cannot change what it reports on. A Python `set.add` is
    not a database write, but the guard cannot tell the two apart from the
    identifier and it should not have to: a name-based ban that starts carving
    out "but this one is only a set" is one argument away from permitting the
    real thing. Cheaper to express this as a comprehension.
    """
    by_agent: dict[int, list[MemoryTransition]] = {}
    for row in rows:
        by_agent.setdefault(row.agent_id, []).append(row)

    return {
        agent_id
        for agent_id, agent_rows in by_agent.items()
        if _has_receded(agent_rows)
    }


def _naive_utc(value: datetime | None) -> datetime | None:
    """Both timestamps as naive UTC, so they can be compared at all.

    NOT COSMETIC, AND IT IS WHY THIS HELPER EXISTS. `created_at` arrives from
    the column's server default and is naive; `decided_at` is set in Python by
    memory_decide as `datetime.now(timezone.utc)` and is AWARE. Comparing them
    raises TypeError, and only for rows decided in the current session - once
    the row has been round-tripped through the database both come back naive
    and the comparison works. So the failure is invisible to any test that
    re-fetches and fires on the live path, which is the wrong way round.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _has_receded(agent_rows: list[MemoryTransition]) -> bool:
    """The three conditions, for one agent's rows. See `_re_enqueued_agents`."""
    decided_times = [
        _naive_utc(r.decided_at) for r in agent_rows if r.decided_at is not None
    ]
    if not decided_times:
        return False
    outstanding = [r for r in agent_rows if r.state not in TERMINAL_STATES]
    if not outstanding:
        return False
    last_decision = max(decided_times)
    return all(
        r.created_at is not None and _naive_utc(r.created_at) > last_decision
        for r in outstanding
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
    # Counted separately from `done` on purpose. See the schema comment: these
    # are terminal and only one of them means the entry is in the new store, so
    # a display that reports only `done` cannot distinguish a migration that
    # worked from one that discarded everything.
    #
    # DWB-622: `written` and `skipped` PARTITION the terminal rows. `journaled`
    # is an OVERLAY over that partition, not a third bucket: it counts rows
    # whose content reached the journal, which is every skip (DWB-594 journals
    # before the row goes terminal) plus any row in the legacy `journaled`
    # state. It therefore overlaps `skipped` by construction and must not be
    # added into a total alongside it.
    #
    # WHY NOT LEAVE IT COUNTING ONLY `TransitionState.journaled`. Nothing in
    # app/ has ever set that state - verified by AST scan and against
    # production, which holds 396 written, 6 skipped and 0 journaled - so the
    # field was structurally incapable of returning a positive. It was not
    # reporting zero because nothing was journaled; it was reporting zero
    # because the state it counted was unreachable, while six journal_entries
    # rows sat there saying otherwise. A counter that cannot produce the
    # positive it is read as producing is the same defect as a guard whose
    # dangerous case answers like its safe one.
    by_outcome = {
        TransitionState.written: 0,
        TransitionState.skipped: 0,
    }
    journaled_overlay = 0
    for row in rows:
        totals = per_agent.setdefault(row.agent_id, [0, 0])
        totals[0] += 1
        if row.state in TERMINAL_STATES:
            totals[1] += 1
        if row.state in by_outcome:
            by_outcome[row.state] += 1
        if row.state in _JOURNALED_STATES:
            journaled_overlay += 1

    re_enqueued_agents = _re_enqueued_agents(rows)

    agents = [
        MemoryTransitionAgentRow(
            agent_id=agent_id,
            agent_name=names.get(agent_id),
            entries_total=total,
            entries_done=done,
            done=total == done,
            re_enqueued=agent_id in re_enqueued_agents,
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
        entries_journaled=journaled_overlay,
        entries_skipped=by_outcome[TransitionState.skipped],
        agents_total=len(agents),
        agents_done=sum(1 for a in agents if a.done),
        agents_re_enqueued=sum(1 for a in agents if a.re_enqueued),
        agents=agents,
    )
