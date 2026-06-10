# Path: app/services/ticket.py
# File: ticket.py
# Created: 2026-03-29
# Purpose: Ticket CRUD, status history, rework detection, time computation, tracking events
# Caller: app/routers/tickets.py
# Callees: models (ticket, status_history, alert, failure_record, agent, project_agent), services/tracking
# Data In: db: Session, TicketCreate/Update
# Data Out: list[Ticket], Ticket
# Last Modified: 2026-06-10

import logging

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
from app.services import tracking as tracking_svc

logger = logging.getLogger(__name__)


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


def _raise_if_jira_disabled(project: Project, jira_issue_key) -> None:
    """DWB-332: refuse jira_issue_key writes when the project is not
    Jira-linked. Idempotent on falsy values (None / "") so callers that
    submit jira_issue_key=null on a non-Jira project still pass through.
    """
    if jira_issue_key and not project.jira_base_url:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "jira_disabled_for_project",
                "message": (
                    f"Project {project.id} ({project.prefix!r}) is not "
                    f"linked to Jira (jira_base_url is null). "
                    f"jira_issue_key cannot be set. Enable Jira on the "
                    f"project via PATCH /api/projects/{project.id} "
                    f"{{\"jira_base_url\": \"...\", "
                    f"\"jira_project_key\": \"...\"}} first."
                ),
                "field": "jira_issue_key",
                "project_id": project.id,
            },
        )


def create_ticket(db: Session, data: TicketCreate) -> Ticket:
    values = data.model_dump()

    # Validate project exists
    project = db.get(Project, values["project_id"])
    if not project:
        raise HTTPException(404, "Project not found")

    # DWB-332: Jira-disabled hard gate at create time.
    _raise_if_jira_disabled(project, values.get("jira_issue_key"))

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

    # DWB-333: sprint_id is NOT NULL in the model — every ticket must belong
    # to a sprint per the hierarchy rule. The TicketUpdate schema declares
    # the field as int | None, so an explicit `{"sprint_id": null}` body
    # passes Pydantic validation but hits MySQL's NOT NULL and produces an
    # opaque 500. Reject it here with a clean 400 telling the caller to
    # reassign instead of detach. epic_id and assigned_agent_id ARE nullable
    # in the model, so null on those is fine and falls through.
    if "sprint_id" in updates and updates["sprint_id"] is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "sprint_id_required",
                "message": (
                    "sprint_id cannot be null. Every ticket must belong to a "
                    "sprint. To detach from the current sprint, reassign to a "
                    "different sprint via {\"sprint_id\": <int>}."
                ),
                "field": "sprint_id",
            },
        )

    # DWB-332: Jira-disabled hard gate on PATCH. Refuses jira_issue_key
    # writes when the project is not linked. Loading the project on every
    # update is a small extra query; acceptable for the safety it adds.
    if "jira_issue_key" in updates and updates["jira_issue_key"]:
        project = db.get(Project, ticket.project_id)
        if project is not None:
            _raise_if_jira_disabled(project, updates["jira_issue_key"])

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

        # DWB-200/211: Auto-insert tracking events on status transitions
        try:
            agent_id = ticket.assigned_agent_id
            if agent_id:
                if updates["status"] == TicketStatus.in_progress:
                    tracking_svc.log_start(db, ticket.id, agent_id)
                elif old_status == TicketStatus.in_progress:
                    tracking_svc.log_stop(db, ticket.id, agent_id)
                elif updates["status"] == TicketStatus.done and old_status != TicketStatus.in_progress:
                    # DWB-211: Ticket skipped in_progress (e.g. todo→done)
                    # Insert both start+stop with current timestamp so every
                    # completed ticket has a tracking record.
                    tracking_svc.log_start(db, ticket.id, agent_id)
                    tracking_svc.log_stop(db, ticket.id, agent_id)
        except Exception as exc:
            logger.warning("Tracking event failed for ticket %s: %s", ticket.id, exc)

        # DWB-143: Detect rework (moved back to in_progress after being done)
        if updates["status"] == TicketStatus.in_progress:
            _check_rework(db, ticket)

        # DWB-144: Recompute time_spent_seconds from status_history
        _recompute_time_in_progress(db, ticket)

    # DWB-353: tokens-not-reported alert removed. It was a relic of the
    # pre-hook workflow that checked ticket.tokens_used == 0 on close; the
    # hook attribution layer (SessionStart/SubagentStop -> hook_sessions
    # -> tracking_log -> by_ticket rollup) made ticket.tokens_used dead
    # for hook-attributed work. The alert fired on every close and was
    # pure noise.
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


def stale_check(db: Session, ticket: Ticket, project_id: int, minutes_stale: int, agent_name: str) -> dict:
    """Check for existing stale alert and create one if none exists. Returns {alert_created, alert_id}."""
    # Dedup: look for an open/acknowledged alert matching this ticket + threshold
    existing = db.scalars(
        select(Alert)
        .where(Alert.ticket_id == ticket.id)
        .where(Alert.status.in_([AlertStatus.open, AlertStatus.acknowledged]))
        .where(Alert.title.contains(ticket.ticket_key))
        .where(Alert.title.contains(f"{minutes_stale}m"))
    ).first()
    if existing:
        return {"alert_created": False, "alert_id": None}

    # Resolve who raises the alert: PM for the project, fallback to ticket's assigned agent
    raiser_id = db.scalars(
        select(Agent.id)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
        .where(Agent.role == "pm")
        .limit(1)
    ).first()
    if not raiser_id:
        raiser_id = ticket.assigned_agent_id
    if not raiser_id:
        # Last resort: any agent on the project
        raiser_id = db.scalars(
            select(ProjectAgent.agent_id)
            .where(ProjectAgent.project_id == project_id)
            .limit(1)
        ).first()
    if not raiser_id:
        raise HTTPException(400, "No agent found for this project to raise the alert")

    alert = Alert(
        project_id=project_id,
        raised_by_agent_id=raiser_id,
        ticket_id=ticket.id,
        title=f"{ticket.ticket_key} stale — in_progress for {minutes_stale}m",
        body=f"Assigned to {agent_name}. Ticket has been in_progress for {minutes_stale} minutes with no updated_at change.",
        severity=AlertSeverity.warning,
        status=AlertStatus.open,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return {"alert_created": True, "alert_id": alert.id}


def delete_ticket(db: Session, ticket: Ticket) -> None:
    db.delete(ticket)
    db.commit()
