# Path: app/routers/project_agents.py
# File: project_agents.py
# Created: 2026-03-29
# Purpose: Project-agent assignment HTTP endpoints
# Caller: app/main.py
# Callees: app/services/project_agent.py
# Data In: HTTP requests
# Data Out: JSON responses (ProjectAgentRead)
# Last Modified: 2026-03-29

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.project_agent import ProjectAgentCreate, ProjectAgentRead
from app.services import project_agent as svc

router = APIRouter(prefix="/api/project-agents", tags=["project-agents"])


@router.get("", response_model=list[ProjectAgentRead])
def list_project_agents(
    project_id: int | None = Query(None),
    agent_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_project_agents(db, project_id=project_id, agent_id=agent_id)


@router.get("/{pa_id}", response_model=ProjectAgentRead)
def get_project_agent(pa_id: int, db: Session = Depends(get_db)):
    pa = svc.get_project_agent(db, pa_id)
    if not pa:
        raise HTTPException(404, "Project-agent assignment not found")
    return pa


@router.post("", response_model=ProjectAgentRead, status_code=201)
def create_project_agent(data: ProjectAgentCreate, db: Session = Depends(get_db)):
    return svc.create_project_agent(db, data)


@router.delete("/{pa_id}", status_code=204)
def delete_project_agent(pa_id: int, db: Session = Depends(get_db)):
    pa = svc.get_project_agent(db, pa_id)
    if not pa:
        raise HTTPException(404, "Project-agent assignment not found")
    svc.delete_project_agent(db, pa)
