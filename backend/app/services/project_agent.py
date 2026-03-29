# Path: app/services/project_agent.py
# File: project_agent.py
# Created: 2026-03-29
# Purpose: Project-agent assignment CRUD
# Caller: app/routers/project_agents.py
# Callees: app/models/project_agent.py
# Data In: db: Session, ProjectAgentCreate
# Data Out: list[ProjectAgent], ProjectAgent
# Last Modified: 2026-03-29

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_agent import ProjectAgent
from app.schemas.project_agent import ProjectAgentCreate


def list_project_agents(
    db: Session,
    project_id: int | None = None,
    agent_id: int | None = None,
) -> list[ProjectAgent]:
    stmt = select(ProjectAgent)
    if project_id:
        stmt = stmt.where(ProjectAgent.project_id == project_id)
    if agent_id:
        stmt = stmt.where(ProjectAgent.agent_id == agent_id)
    return list(db.scalars(stmt).all())


def get_project_agent(db: Session, pa_id: int) -> ProjectAgent | None:
    return db.get(ProjectAgent, pa_id)


def create_project_agent(db: Session, data: ProjectAgentCreate) -> ProjectAgent:
    pa = ProjectAgent(**data.model_dump())
    db.add(pa)
    db.commit()
    db.refresh(pa)
    return pa


def delete_project_agent(db: Session, pa: ProjectAgent) -> None:
    db.delete(pa)
    db.commit()
