# Path: app/services/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Project CRUD with overhead increment and cascading delete
# Caller: app/routers/projects.py
# Callees: app/models/project.py and all related models
# Data In: db: Session, ProjectCreate/Update
# Data Out: list[Project], Project
# Last Modified: 2026-06-22

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.agent import Agent
from app.models.agent_consolidation_ack import AgentConsolidationAck
from app.models.agent_score import AgentScore
from app.models.alert import Alert
from app.models.comment import Comment
from app.models.dwb_session import DwbSession
from app.models.epic import Epic
from app.models.failure_record import FailureRecord
from app.models.hook_session import HookSession
from app.models.instruction import Instruction
from app.models.project import Project, ProjectStatus
from app.models.project_agent import ProjectAgent
from app.models.score_event import ScoreEvent
from app.models.sprint import Sprint
from app.models.status_history import StatusHistory
from app.models.test_result import TestResult
from app.models.ticket import Ticket
from app.models.tool_action import ToolAction
from app.models.tracking_log import TrackingLog
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
    # Get all sprint IDs to clear sprint-scoped child rows (consolidation acks)
    sprint_ids = list(
        db.scalars(select(Sprint.id).where(Sprint.project_id == pid)).all()
    )
    if ticket_ids:
        # Delete comments on project tickets
        db.execute(delete(Comment).where(Comment.ticket_id.in_(ticket_ids)))
        # Delete alerts linked to project tickets
        db.execute(delete(Alert).where(Alert.ticket_id.in_(ticket_ids)))
        # Delete failure records referencing project tickets
        db.execute(delete(FailureRecord).where(FailureRecord.ticket_id.in_(ticket_ids)))
        # Delete status history for project tickets
        db.execute(delete(StatusHistory).where(StatusHistory.ticket_id.in_(ticket_ids)))
    # Delete failure records directly on project (ticket_id may be null)
    db.execute(delete(FailureRecord).where(FailureRecord.project_id == pid))
    # Delete alerts directly on project (ticket_id may be null)
    db.execute(delete(Alert).where(Alert.project_id == pid))
    # Delete test results (may reference sprints/tickets in this project)
    db.execute(delete(TestResult).where(TestResult.project_id == pid))
    # Delete tracking logs
    db.execute(delete(TrackingLog).where(TrackingLog.project_id == pid))
    # Delete activity logs
    db.execute(delete(ActivityLog).where(ActivityLog.project_id == pid))
    # Delete instructions
    db.execute(delete(Instruction).where(Instruction.project_id == pid))
    # DWB-424/425: clear the scoring ledger + derived cache before the sprints
    # and project they reference are deleted (no ON DELETE CASCADE on these FKs).
    db.execute(delete(ScoreEvent).where(ScoreEvent.project_id == pid))
    db.execute(delete(AgentScore).where(AgentScore.project_id == pid))
    # DWB-417/421: tool_actions linked to this project's DWB sessions must go
    # before those sessions (the dwb_session_id FK has no cascade). Ticket-linked
    # tool_actions cascade with their tickets below; agent-linked-only rows have
    # no project FK and are left (agents are global, not deleted).
    dwb_session_ids = list(
        db.scalars(select(DwbSession.id).where(DwbSession.project_id == pid)).all()
    )
    if dwb_session_ids:
        db.execute(
            delete(ToolAction).where(ToolAction.dwb_session_id.in_(dwb_session_ids))
        )
    # Delete hook sessions (FK to project, sprints, dwb_sessions, tickets) before
    # those parents go away.
    db.execute(delete(HookSession).where(HookSession.project_id == pid))
    # Delete DWB sessions on this project
    db.execute(delete(DwbSession).where(DwbSession.project_id == pid))
    # Delete consolidation acks tied to this project's sprints before the sprints
    if sprint_ids:
        db.execute(
            delete(AgentConsolidationAck).where(
                AgentConsolidationAck.sprint_id.in_(sprint_ids)
            )
        )
    # Delete tickets
    db.execute(delete(Ticket).where(Ticket.project_id == pid))
    # Delete project agents (the membership join)
    db.execute(delete(ProjectAgent).where(ProjectAgent.project_id == pid))
    # Detach agents homed on this project. Agents are global identities (name is
    # unique system-wide and they may carry history on OTHER projects), so we
    # null their home project_id rather than delete them.
    db.execute(update(Agent).where(Agent.project_id == pid).values(project_id=None))
    # Delete sprints
    db.execute(delete(Sprint).where(Sprint.project_id == pid))
    # Delete epics
    db.execute(delete(Epic).where(Epic.project_id == pid))
    # Delete project
    db.delete(project)
    db.commit()
