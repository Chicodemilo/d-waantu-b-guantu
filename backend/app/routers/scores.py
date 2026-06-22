# Path: app/routers/scores.py
# File: scores.py
# Created: 2026-06-22
# Purpose: HTTP read API for agent scoring (DWB-424) - project leaderboard, per-agent score detail + ledger, and a cache rebuild utility.
# Caller: app/main.py
# Callees: app/services/scoring.py, app/models/project.py, app/models/agent.py
# Data In: HTTP GET/POST
# Data Out: LeaderboardRow[], AgentScoreDetail, rebuild result
# Last Modified: 2026-06-22

"""Agent scoring read API (DWB-424)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.models.project import Project
from app.schemas.score import AgentScoreDetail, LeaderboardRow
from app.services import scoring as svc

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


@router.post("/projects/{project_id}/scores/rebuild")
def rebuild_project_scores(project_id: int, db: Session = Depends(get_db)):
    """Recompute the agent_score cache for a project from the ledger. The
    ledger is authoritative; this is the recovery path if the cache drifts."""
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    touched = svc.rebuild_agent_scores(db, project_id)
    return {"status": "ok", "project_id": project_id, "agents_rebuilt": touched}
