# Path: app/routers/agents.py
# File: agents.py
# Created: 2026-03-29
# Purpose: Agent HTTP endpoints — CRUD
# Caller: app/main.py
# Callees: app/services/agent.py
# Data In: HTTP requests
# Data Out: JSON responses (AgentRead)
# Last Modified: 2026-03-29

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.agent import AgentCreate, AgentRead, AgentUpdate
from app.services import agent as svc

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentRead])
def list_agents(
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_agents(db, role=role, is_active=is_active)


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: int, db: Session = Depends(get_db)):
    agent = svc.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.post("", response_model=AgentRead, status_code=201)
def create_agent(data: AgentCreate, db: Session = Depends(get_db)):
    return svc.create_agent(db, data)


@router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: int, data: AgentUpdate, db: Session = Depends(get_db)
):
    agent = svc.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return svc.update_agent(db, agent, data)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(agent_id: int, db: Session = Depends(get_db)):
    agent = svc.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    svc.delete_agent(db, agent)
