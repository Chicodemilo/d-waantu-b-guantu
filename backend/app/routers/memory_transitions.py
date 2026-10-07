# Path: app/routers/memory_transitions.py
# File: memory_transitions.py
# Created: 2026-09-30 (DWB-594)
# Purpose: The adopt pipeline's HTTP surface - the dry-run plan, ONE candidate
#          at a time, the decision, and the sweep. Starting a transition is the
#          project PATCH and is deliberately not here.
# Caller: app/main.py
# Callees: app/services/memory_adopt, memory_decide, memory_sweep
# Data In: HTTP requests
# Data Out: JSON (the plan, one candidate, a decision result, a sweep result)
# Last Modified: 2026-09-30 (DWB-594)

"""The decide loop's endpoints.

THERE IS NO ROUTE HERE THAT RETURNS EVERY CANDIDATE, and that absence is the
ticket rather than an oversight. Miles: "I don't want to leave it to just a
giant context list." `GET /next` hands over one entry; progress is a count.

THE PLAN IS THE ONE EXCEPTION AND IT IS NOT A LOOPHOLE. It returns every
candidate, but it writes nothing, creates no run, and exists to be read by a
HUMAN deciding whether to begin. It is also available before the transition
starts, which is the only moment the answer is actionable. What it deliberately
does NOT carry is a proposed tier: section 4 rules the snapshot makes no
judgement, and an agent shown a proposed answer agrees with it, which is the
rubber-stamp the design exists to prevent.

STARTING A TRANSITION IS NOT HERE. It is `PATCH /api/projects/{id}` with
`memory_mode`, because DWB-593's legal-edge table already governs that route and
a second entry point would be a second copy of the rule.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.memory_transition import MemoryTransition, TransitionState
from app.models.project import Project
from app.services import (
    memory_adopt,
    memory_cutover,
    memory_decide,
    memory_origin,
    memory_sweep,
)
from app.services import project as project_svc

router = APIRouter(prefix="/api/memory-transitions", tags=["memory_transitions"])
project_router = APIRouter(prefix="/api/projects", tags=["memory_transitions"])


class DecideRequest(BaseModel):
    """Body for one decision.

    `tier` omitted (or null) means SKIP, which journals the entry first. A
    separate /skip route would let a caller reach the skip path without going
    through the code that journals, so the two share one entry point on purpose.
    """

    tier: str | None = None
    decided_by: str
    reason: str | None = None


def _project_or_404(db: Session, project_id: int) -> Project:
    project = project_svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(404, f"project {project_id} not found")
    return project


def _serialize(row: MemoryTransition) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "agent_id": row.agent_id,
        "run_id": row.run_id,
        "state": row.state.value,
        "source_excerpt": row.source_excerpt,
        "decided_tier": row.decided_tier.value if row.decided_tier else None,
        "decided_by": row.decided_by,
        # Surfaced so the read-back endpoint can answer WHY, not only what. An
        # agent correcting its own mis-tier remembers the call it regrets and
        # looks the row up by id; the tier alone does not tell it whether the
        # decision was considered or rushed.
        "reason": row.reason,
        "target_memory_id": row.target_memory_id,
    }


@project_router.get("/{project_id}/memory-transition/plan")
def transition_plan(project_id: int, db: Session = Depends(get_db)):
    """DRY RUN. Every candidate an adoption would enumerate. Writes nothing.

    DWB-594 acceptance 5. Callable before the transition starts, which is the
    moment the answer is actionable - a plan you can only see after committing
    to the work answers the question too late.

    Carries no proposed tier: the snapshot makes no judgement (spec section 4),
    so this shows what will be ASKED rather than what will be answered.
    """
    project = _project_or_404(db, project_id)
    result = memory_adopt.plan(db, project)
    return {
        "project_id": project.id,
        "candidate_count": result.candidate_count,
        "agents_seen": result.agents_seen,
        "agents_with_no_memory": result.agents_with_no_memory,
        # Surfaced rather than swallowed: a file that cannot be read looks
        # exactly like a file with no lessons, and only one of those is safe to
        # adopt past.
        "unreadable": result.unreadable,
        "content_without_candidates": result.content_without_candidates,
        "would_refuse": result.is_defective,
        "candidates": [
            {"agent_id": row.agent_id, "source_excerpt": row.source_excerpt}
            for row in result.rows
        ],
    }


@project_router.get("/{project_id}/memory-transition/next")
def next_candidate(
    project_id: int,
    agent_id: int = Query(..., description="Whose memory is being adopted."),
    db: Session = Depends(get_db),
):
    """ONE candidate, or null when this agent is done.

    Never a list. The constraint the lane exists to protect: an agent is handed
    one entry and one question, not its file.
    """
    _project_or_404(db, project_id)
    row = memory_decide.next_entry(db, agent_id=agent_id)
    return {
        "entry": _serialize(row) if row is not None else None,
        # A count, not the queue. A number cannot be pasted into a prompt.
        "remaining": memory_decide.remaining_count(db, agent_id=agent_id),
    }


@router.post("/{transition_id}/decide")
def decide_candidate(
    transition_id: int, data: DecideRequest, db: Session = Depends(get_db)
):
    """Record a tier for one candidate, or skip it (journaling it first).

    The cutover fires here when this is the last entry, because the mode change
    is the pipeline finishing rather than a separate act.

    Errors: 400 for a refused tier, an already-decided row, or NO OPEN DWB
    SESSION (DWB-637 - checked per decision, so a session closing mid-adoption
    stops the run here rather than silently returning every remaining row to a
    NULL clock origin); 404 unknown; 409 when the decision completed a run that
    must not land (every entry skipped, so nothing was preserved).
    """
    try:
        row, landed = memory_decide.decide_and_maybe_cut_over(
            db,
            transition_id=transition_id,
            tier=data.tier,
            decided_by=data.decided_by,
            reason=data.reason,
        )
    except memory_origin.MemoryOriginMissing as e:
        # DWB-637. Raised before the transition row is touched, so the entry is
        # still decidable and the run resumes from here once a session is open.
        raise HTTPException(400, e.detail)
    except memory_decide.DecideError as e:
        raise HTTPException(404 if e.code == "not_found" else 400, e.detail)
    except memory_cutover.CutoverRefused as e:
        # 409: the decision itself was valid, but it completed a run whose
        # result must not be applied, so NOTHING from this request lands and the
        # entry stays decidable.
        #
        # No explicit rollback. `get_db` only closes the session, and an
        # uncommitted session discards its work on close, so raising here is
        # already all-or-nothing. Calling rollback() would additionally unwind
        # the caller's transaction, which under the test harness is the outer
        # one the whole test is running in - it took the fixture's own rows with
        # it and turned a correct 409 into a vanished project.
        raise HTTPException(409, str(e))
    db.commit()
    db.refresh(row)
    return {
        "entry": _serialize(row),
        "landed_in": landed.value if landed is not None else None,
        "remaining": memory_decide.remaining_count(db, agent_id=row.agent_id),
    }


@project_router.post("/{project_id}/memory-transition/sweep")
def run_sweep(
    project_id: int,
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Pick up anything written since the snapshot.

    Repeat until `is_empty` is true; only then can the run finish. Memory keeps
    being written during the judgement loop, which is exactly why the loop
    cannot be the freeze.
    """
    project = _project_or_404(db, project_id)
    run = project_svc.open_run(db, project.id)
    if run is None:
        raise HTTPException(
            409,
            f"project {project_id} has no open memory transition to sweep. "
            "Start one by PATCHing memory_mode.",
        )
    result = memory_sweep.sweep(db, project, run, persist=not dry_run)
    if not dry_run:
        db.commit()
    return {
        "added": result.added_count,
        "is_empty": result.is_empty,
        "dry_run": dry_run,
        "unreadable": result.unreadable,
        "content_without_candidates": result.content_without_candidates,
        "would_refuse": result.is_defective,
    }


# The states a row can be in AFTER a judgement has been made. Deliberately a
# named set rather than "not pending": a state added later is excluded until
# someone decides it belongs, which is the safe direction.
DECIDED_STATES = (
    TransitionState.written,
    TransitionState.skipped,
    TransitionState.journaled,
)


@router.get("/{transition_id}")
def get_decided_entry(transition_id: int, db: Session = Depends(get_db)):
    """ONE decided entry, by id. DWB-626, narrowed by Archie's ruling.

    THIS WAS A LISTING AND THE GUARD WAS RIGHT TO REFUSE IT. The first version
    returned every decided entry for an agent. DWB-594's structural check caught
    it on its first run, and the two tickets genuinely conflict: DWB-626 asks
    that a tiering decision be reviewable, DWB-594 forbids handing an agent the
    queue. The ruling is that the guard wins and this feature gets narrower,
    because the reason behind the guard is undamaged - AN AGENT SHOWN THE QUEUE
    REASONS ABOUT THE QUEUE, and one entry at a time is the whole design.

    A lookup by id gives review and undo without ever handing over a set. The
    caller must already know which decision it is asking about, which is exactly
    the position an agent correcting its own mis-tier is in: it remembers the
    call it regrets. What it could not do before was read back what it actually
    recorded.

    Refuses a row that is still PENDING. An undecided candidate reached by
    direct id would be the one-entry handover the decide endpoint already owns,
    with none of its bookkeeping - and `next_entry` is the only thing allowed to
    choose which candidate an agent sees.
    """
    row = db.get(MemoryTransition, transition_id)
    if row is None:
        raise HTTPException(404, f"transition {transition_id} not found")
    if row.state not in DECIDED_STATES:
        raise HTTPException(
            409,
            f"transition {transition_id} is {row.state.value}, not decided. This "
            "endpoint reads back a DECISION; an undecided candidate is handed "
            "over by GET /api/projects/{project_id}/memory-transition/next, "
            "which is the only path allowed to choose what an agent sees.",
        )
    return _serialize(row)
