# Path: app/services/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Project CRUD with overhead increment and cascading delete
# Caller: app/routers/projects.py
# Callees: app/models/project.py and all related models
# Data In: db: Session, ProjectCreate/Update
# Data Out: list[Project], Project
# Last Modified: 2026-03-29

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.alert import Alert
from app.models.comment import Comment
from app.models.epic import Epic
from app.models.instruction import Instruction
from app.models.project import Project, ProjectStatus
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint
from app.models.test_result import TestResult
from app.models.ticket import Ticket
from app.schemas.project import ProjectCreate, ProjectUpdate


def list_projects(db: Session, status: ProjectStatus | None = None) -> list[Project]:
    stmt = select(Project)
    if status:
        stmt = stmt.where(Project.status == status)
    stmt = stmt.order_by(Project.created_at.desc())
    return list(db.scalars(stmt).all())


def get_project(db: Session, project_id: int) -> Project | None:
    return db.get(Project, project_id)


def create_project(db: Session, data: ProjectCreate) -> Project:
    project = Project(**data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


def increment_overhead(db: Session, project: Project, role: str, tokens_used: int, time_spent_seconds: int = 0) -> Project:
    if role == "team_lead":
        project.tl_overhead_tokens += tokens_used
        project.tl_overhead_time_seconds += time_spent_seconds
    elif role == "pm":
        project.pm_overhead_tokens += tokens_used
        project.pm_overhead_time_seconds += time_spent_seconds
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    pid = project.id
    # Get all ticket IDs for this project to delete child records
    ticket_ids = list(
        db.scalars(select(Ticket.id).where(Ticket.project_id == pid)).all()
    )
    if ticket_ids:
        # Delete comments on project tickets
        db.execute(delete(Comment).where(Comment.ticket_id.in_(ticket_ids)))
        # Delete alerts linked to project tickets
        db.execute(delete(Alert).where(Alert.ticket_id.in_(ticket_ids)))
    # Delete alerts directly on project (ticket_id may be null)
    db.execute(delete(Alert).where(Alert.project_id == pid))
    # Delete test results (may reference sprints/tickets in this project)
    db.execute(delete(TestResult).where(TestResult.project_id == pid))
    # Delete activity logs
    db.execute(delete(ActivityLog).where(ActivityLog.project_id == pid))
    # Delete instructions
    db.execute(delete(Instruction).where(Instruction.project_id == pid))
    # Delete tickets
    db.execute(delete(Ticket).where(Ticket.project_id == pid))
    # Delete project agents
    db.execute(delete(ProjectAgent).where(ProjectAgent.project_id == pid))
    # Delete sprints
    db.execute(delete(Sprint).where(Sprint.project_id == pid))
    # Delete epics
    db.execute(delete(Epic).where(Epic.project_id == pid))
    # Delete project
    db.delete(project)
    db.commit()
