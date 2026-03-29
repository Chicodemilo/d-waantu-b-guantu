# Path: app/services/ticket.py
# File: ticket.py
# Created: 2026-03-29
# Purpose: Ticket CRUD, status history, rework detection, time computation
# Caller: app/routers/tickets.py
# Callees: models (ticket, status_history, alert, failure_record, agent, project_agent)
# Data In: db: Session, TicketCreate/Update
# Data Out: list[Ticket], Ticket
# Last Modified: 2026-03-29

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.failure_record import FailureRecord
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.models.status_history import StatusHistory
from app.models.sprint import Sprint, SprintStatus
from app.models.ticket import Ticket, TicketStatus, TicketType
from app.schemas.ticket import TicketCreate, TicketUpdate


def list_tickets(
    db: Session,
    project_id: int | None = None,
    sprint_id: int | None = None,
    epic_id: int | None = None,
    assigned_agent_id: int | None = None,
    status: TicketStatus | None = None,
    ticket_type: TicketType | None = None,
) -> list[Ticket]:
    stmt = select(Ticket)
    if project_id:
        stmt = stmt.where(Ticket.project_id == project_id)
    if sprint_id:
        stmt = stmt.where(Ticket.sprint_id == sprint_id)
    if epic_id:
        stmt = stmt.where(Ticket.epic_id == epic_id)
    if assigned_agent_id:
        stmt = stmt.where(Ticket.assigned_agent_id == assigned_agent_id)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if ticket_type:
        stmt = stmt.where(Ticket.ticket_type == ticket_type)
    stmt = stmt.order_by(Ticket.created_at.desc())
    return list(db.scalars(stmt).all())


def get_ticket(db: Session, ticket_id: int) -> Ticket | None:
    return db.get(Ticket, ticket_id)


def create_ticket(db: Session, data: TicketCreate) -> Ticket:
    values = data.model_dump()

    # Validate project exists
    project = db.get(Project, values["project_id"])
    if not project:
        raise HTTPException(404, "Project not found")

    # Auto-assign sprint_id if not provided
    if values.get("sprint_id") is None:
        sprint = db.scalars(
            select(Sprint)
            .where(Sprint.project_id == values["project_id"])
            .where(Sprint.status == SprintStatus.active)
            .order_by(Sprint.created_at.desc())
            .limit(1)
        ).first()
        if not sprint:
            raise HTTPException(400, "No active sprint found for this project. Create an active sprint first or provide sprint_id.")
        values["sprint_id"] = sprint.id
    else:
        sprint = db.get(Sprint, values["sprint_id"])
        if not sprint:
            raise HTTPException(404, "Sprint not found")

    # Auto-assign epic_id from sprint if not provided
    if values.get("epic_id") is None and sprint:
        values["epic_id"] = sprint.epic_id

    ticket = Ticket(**values)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def update_ticket(db: Session, ticket: Ticket, data: TicketUpdate) -> Ticket:
    updates = data.model_dump(exclude_unset=True)
    old_status = ticket.status

    for key, value in updates.items():
        setattr(ticket, key, value)
    db.commit()
    db.refresh(ticket)

    status_changed = "status" in updates and updates["status"] != old_status

    # Record status change in history
    if status_changed:
        new_status_val = updates["status"].value if hasattr(updates["status"], "value") else str(updates["status"])
        old_status_val = old_status.value if hasattr(old_status, "value") else str(old_status)
        db.add(StatusHistory(
            ticket_id=ticket.id,
            old_status=old_status_val,
            new_status=new_status_val,
            changed_by_agent_id=ticket.assigned_agent_id,
        ))
        db.commit()

        # DWB-143: Detect rework (moved back to in_progress after being done)
        if updates["status"] == TicketStatus.in_progress:
            _check_rework(db, ticket)

        # DWB-144: Recompute time_spent_seconds from status_history
        _recompute_time_in_progress(db, ticket)

    # Auto-create alert when ticket closed with no tokens reported
    if (
        updates.get("status") == TicketStatus.done
        and ticket.tokens_used == 0
        and ticket.assigned_agent_id is not None
    ):
        alert = Alert(
            project_id=ticket.project_id,
            raised_by_agent_id=ticket.assigned_agent_id,
            ticket_id=ticket.id,
            title=f"Tokens not reported for {ticket.ticket_key}",
            body="Agent should POST to /api/tickets/:id/tokens before closing.",
            severity=AlertSeverity.info,
            status=AlertStatus.open,
        )
        db.add(alert)
        db.commit()

    return ticket


def _check_rework(db: Session, ticket: Ticket) -> None:
    """If ticket was previously 'done', this is rework — create failure record + PM alert."""
    prev_done = db.scalar(
        select(StatusHistory.id)
        .where(StatusHistory.ticket_id == ticket.id)
        .where(StatusHistory.new_status == "done")
        .limit(1)
    )
    if not prev_done:
        return

    # Find PM agent for this project
    pm_agent_id = db.scalars(
        select(Agent.id)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == ticket.project_id)
        .where(Agent.role == "pm")
        .limit(1)
    ).first()
    if not pm_agent_id:
        return

    agent_id = ticket.assigned_agent_id or pm_agent_id

    db.add(FailureRecord(
        project_id=ticket.project_id,
        ticket_id=ticket.id,
        sprint_id=ticket.sprint_id,
        agent_id=agent_id,
        logged_by_agent_id=pm_agent_id,
        failure_type="rework",
        severity="medium",
        attempt_number=1,
        notes=f"Auto-detected rework: {ticket.ticket_key} moved back to in_progress after being done.",
        resolved=False,
    ))

    db.add(Alert(
        project_id=ticket.project_id,
        raised_by_agent_id=pm_agent_id,
        ticket_id=ticket.id,
        title=f"Rework detected: {ticket.ticket_key}",
        body=f"{ticket.ticket_key} was moved back to in_progress after being marked done. A failure record has been created.",
        severity=AlertSeverity.info,
        status=AlertStatus.open,
    ))
    db.commit()


def _recompute_time_in_progress(db: Session, ticket: Ticket) -> None:
    """Compute total time spent in 'in_progress' from status_history and update ticket."""
    history = list(db.scalars(
        select(StatusHistory)
        .where(StatusHistory.ticket_id == ticket.id)
        .order_by(StatusHistory.changed_at.asc())
    ).all())

    total_seconds = 0
    in_progress_since = None

    for entry in history:
        if entry.new_status == "in_progress":
            in_progress_since = entry.changed_at
        elif in_progress_since is not None and entry.old_status == "in_progress":
            delta = (entry.changed_at - in_progress_since).total_seconds()
            total_seconds += delta
            in_progress_since = None

    # If currently in_progress, don't count open interval (no end time yet)

    if total_seconds > 0 and int(total_seconds) != ticket.time_spent_seconds:
        ticket.time_spent_seconds = int(total_seconds)
        db.commit()
        db.refresh(ticket)


def increment_tokens(
    db: Session, ticket: Ticket, tokens_used: int, time_spent_seconds: int, source: str | None = None
) -> Ticket:
    ticket.tokens_used += tokens_used
    ticket.time_spent_seconds += time_spent_seconds
    if source:
        ticket.token_source = source
    db.commit()
    db.refresh(ticket)
    return ticket


def get_token_attribution(db: Session, ticket: Ticket) -> dict:
    return {
        "ticket_key": ticket.ticket_key,
        "tokens_used": ticket.tokens_used,
        "time_spent_seconds": ticket.time_spent_seconds,
        "source": ticket.token_source or "unknown",
        "history": [],
    }


def get_ticket_history(db: Session, ticket_id: int) -> list[StatusHistory]:
    stmt = (
        select(StatusHistory)
        .where(StatusHistory.ticket_id == ticket_id)
        .order_by(StatusHistory.changed_at.asc())
    )
    return list(db.scalars(stmt).all())


def delete_ticket(db: Session, ticket: Ticket) -> None:
    db.delete(ticket)
    db.commit()
