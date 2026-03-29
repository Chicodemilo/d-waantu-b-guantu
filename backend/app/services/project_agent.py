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
