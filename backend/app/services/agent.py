# Path: app/services/agent.py
# File: agent.py
# Created: 2026-03-29
# Purpose: Agent CRUD operations
# Caller: app/routers/agents.py
# Callees: app/models/agent.py
# Data In: db: Session, AgentCreate/Update
# Data Out: list[Agent], Agent
# Last Modified: 2026-03-29

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate


def list_agents(
    db: Session,
    role: str | None = None,
    is_active: bool | None = None,
) -> list[Agent]:
    stmt = select(Agent)
    if role:
        stmt = stmt.where(Agent.role == role)
    if is_active is not None:
        stmt = stmt.where(Agent.is_active == is_active)
    stmt = stmt.order_by(Agent.created_at.desc())
    return list(db.scalars(stmt).all())


def get_agent(db: Session, agent_id: int) -> Agent | None:
    return db.get(Agent, agent_id)


def create_agent(db: Session, data: AgentCreate) -> Agent:
    agent = Agent(**data.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def update_agent(db: Session, agent: Agent, data: AgentUpdate) -> Agent:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    return agent


def delete_agent(db: Session, agent: Agent) -> None:
    db.delete(agent)
    db.commit()
