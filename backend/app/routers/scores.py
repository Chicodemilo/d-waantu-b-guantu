# Path: app/routers/scores.py
# File: scores.py
# Created: 2026-06-22
# Purpose: HTTP API for agent scoring (DWB-424 read; DWB-426 human write; DWB-427 peer economy) - leaderboard, per-agent detail + ledger (by id or name), human carrot/stick award + team broadcast, cache rebuild.
# Caller: app/main.py
# Callees: app/services/scoring.py, app/models/project.py, app/models/agent.py
# Data In: HTTP GET/POST
# Data Out: LeaderboardRow[], AgentScoreDetail, HumanScoreResponse, rebuild result
# Last Modified: 2026-06-23 (DWB-432: request logging on award/peer/rebuild + reject paths)

"""Agent scoring read API (DWB-424)."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.models.project import Project
from app.schemas.score import (
    AgentScoreDetail,
    HumanScoreRequest,
    HumanScoreResponse,
    LeaderboardRow,
    PeerScoreRequest,
    PeerScoreResponse,
)
from app.services import scoring as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["scores"])


@router.get("/projects/{project_id}/scores", response_model=list[LeaderboardRow])
def get_project_scores(project_id: int, db: Session = Depends(get_db)):
    """Project leaderboard: per-agent reputation (all-time), this-sprint delta,
    and remaining influence, sorted top score first."""
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    return svc.get_leaderboard(db, project_id)


@router.get("/agents/{agent_id}/score", response_model=AgentScoreDetail)
def get_agent_score(
    agent_id: int,
    project_id: int | None = Query(
        None, description="Defaults to the agent's home project_id"
    ),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """One agent's score summary + reasoned ledger (AgentPage view).

    ``project_id`` defaults to the agent's home project when omitted, since
    scores are per-(agent, project).
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    pid = project_id if project_id is not None else agent.project_id
    if pid is None:
        raise HTTPException(
            400, "project_id required (agent has no home project)"
        )

    summary = svc.get_agent_summary(db, agent_id, pid)
    ledger = svc.get_agent_ledger(db, agent_id, pid, limit=limit)
    return {**summary, "ledger": ledger}


@router.get("/projects/{project_id}/scores/agent", response_model=AgentScoreDetail)
def get_project_agent_score(
    project_id: int,
    agent: str = Query(..., description="Agent name or id (for /score <agent>)"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Look up one agent's score detail + ledger by NAME or id within a project
    (DWB-426). Backs the /score <agent> slash command, which passes a name."""
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    resolved = svc.resolve_agent_ref(db, agent)
    if resolved is None:
        raise HTTPException(404, f"Agent not found: {agent!r}")
    summary = svc.get_agent_summary(db, resolved.id, project_id)
    ledger = svc.get_agent_ledger(db, resolved.id, project_id, limit=limit)
    return {**summary, "ledger": ledger}


@router.post(
    "/projects/{project_id}/scores/award",
    response_model=HumanScoreResponse,
    status_code=201,
)
def award_human_score(
    project_id: int, data: HumanScoreRequest, db: Session = Depends(get_db)
):
    """Human carrot/stick (DWB-426): award (delta>0) or dock (delta<0) an
    agent's reputation, free of influence cost, and broadcast it to the whole
    team at elevated severity. Subject is resolved by name or id."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if data.delta == 0:
        logger.warning("award rejected: zero delta (project %s, agent %r)", project_id, data.agent)
        raise HTTPException(400, "delta must be non-zero (positive carrot / negative stick)")
    subject = svc.resolve_agent_ref(db, data.agent)
    if subject is None:
        logger.warning("award rejected: agent not found %r (project %s)", data.agent, project_id)
        raise HTTPException(404, f"Agent not found: {data.agent!r}")
    # DWB-430: scores are per-project; the subject must be on this project.
    if not svc.is_project_member(db, subject.id, project_id):
        logger.warning(
            "award rejected: %s not on project %s", subject.name, project.prefix
        )
        raise HTTPException(
            404, f"Agent {subject.name!r} is not on project {project.prefix}"
        )

    event, broadcast_count = svc.human_score(
        db, project_id=project_id, subject=subject,
        delta=data.delta, reason=data.reason,
    )
    summary = svc.get_agent_summary(db, subject.id, project_id)
    return {
        "status": "ok",
        "event_id": event.id,
        "subject_agent_id": subject.id,
        "subject_name": subject.name,
        "delta": event.delta,
        "trigger_type": event.trigger_type.value,
        "reputation": summary["reputation"],
        "sprint_delta": summary["sprint_delta"],
        "broadcast_count": broadcast_count,
    }


@router.post(
    "/projects/{project_id}/scores/peer",
    response_model=PeerScoreResponse,
    status_code=201,
)
def peer_score(
    project_id: int,
    data: PeerScoreRequest,
    x_agent_id: int | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Peer carrot/stick (DWB-427): the acting agent (X-Agent-ID) spends
    influence to move a peer's reputation. delta>0 grant, delta<0 demerit.
    Anti-gaming caps (no self-scoring, influence budget, per-action and
    per-target-per-sprint limits) are enforced in the service and surface as
    HTTP 400 with a clear message."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if x_agent_id is None:
        logger.warning("peer rejected: missing X-Agent-ID (project %s)", project_id)
        raise HTTPException(400, "X-Agent-ID header is required to identify the acting agent")
    actor = db.get(Agent, x_agent_id)
    if actor is None:
        logger.warning("peer rejected: acting agent %s not found", x_agent_id)
        raise HTTPException(404, f"Acting agent not found: {x_agent_id}")
    # DWB-430: both actor and subject must belong to this project.
    if not svc.is_project_member(db, actor.id, project_id):
        logger.warning("peer rejected: actor %s not on project %s", actor.name, project.prefix)
        raise HTTPException(
            404, f"Agent {actor.name!r} is not on project {project.prefix}"
        )
    subject = svc.resolve_agent_ref(db, data.subject)
    if subject is None:
        logger.warning("peer rejected: subject not found %r (project %s)", data.subject, project_id)
        raise HTTPException(404, f"Subject agent not found: {data.subject!r}")
    if not svc.is_project_member(db, subject.id, project_id):
        logger.warning("peer rejected: subject %s not on project %s", subject.name, project.prefix)
        raise HTTPException(
            404, f"Agent {subject.name!r} is not on project {project.prefix}"
        )

    event, broadcast_count = svc.peer_score(
        db, project_id=project_id, actor=actor, subject=subject,
        delta=data.delta, reason=data.reason,
    )
    summary = svc.get_agent_summary(db, subject.id, project_id)
    return {
        "status": "ok",
        "event_id": event.id,
        "actor_agent_id": actor.id,
        "subject_agent_id": subject.id,
        "subject_name": subject.name,
        "delta": event.delta,
        "trigger_type": event.trigger_type.value,
        "subject_reputation": summary["reputation"],
        "actor_influence_remaining": svc.remaining_influence(db, actor.id, project_id),
        "broadcast_count": broadcast_count,
    }


@router.post("/projects/{project_id}/scores/rebuild")
def rebuild_project_scores(project_id: int, db: Session = Depends(get_db)):
    """Recompute the agent_score cache for a project from the ledger. The
    ledger is authoritative; this is the recovery path if the cache drifts."""
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    touched = svc.rebuild_agent_scores(db, project_id)
    return {"status": "ok", "project_id": project_id, "agents_rebuilt": touched}
