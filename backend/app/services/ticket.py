# Path: app/services/ticket.py
# File: ticket.py
# Created: 2026-03-29
# Purpose: Ticket CRUD, status history, rework detection, time computation, tracking events, semantic activity events (DWB-409), auto-scoring triggers (DWB-425)
# Caller: app/routers/tickets.py
# Callees: models (ticket, status_history, alert, failure_record, agent, project_agent), services/tracking, services/activity_log, services/scoring_triggers
# Data In: db: Session, TicketCreate/Update, acting_agent_id
# Data Out: list[Ticket], Ticket
# Last Modified: 2026-06-24 (DWB-455: sub-task parent validation + epic/sprint inheritance)

import logging
from datetime import datetime

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
from app.services import scoring_triggers
from app.services import tracking as tracking_svc
from app.services.activity_log import log_activity

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


def _resolve_subtask_parent(
    db: Session,
    *,
    ticket_type: TicketType,
    parent_ticket_id: int | None,
    project_id: int,
    this_ticket_id: int | None = None,
) -> Ticket | None:
    """DWB-455: validate the (ticket_type, parent_ticket_id) pair and return
    the resolved parent Ticket (or None for non-subtasks). Raises HTTP 400 on
    any rule violation. Rules:

      - ticket_type=subtask REQUIRES parent_ticket_id; other types must leave
        it null.
      - parent must exist and be in the same project.
      - parent cannot itself be a subtask (one level only, matching Jira).
      - a ticket cannot be its own parent.
    """
    is_subtask = ticket_type == TicketType.subtask

    if not is_subtask:
        if parent_ticket_id is not None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "parent_only_on_subtask",
                    "message": (
                        "parent_ticket_id may only be set when "
                        "ticket_type='subtask'. Clear parent_ticket_id or set "
                        "ticket_type to subtask."
                    ),
                    "field": "parent_ticket_id",
                },
            )
        return None

    # is_subtask
    if parent_ticket_id is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "subtask_requires_parent",
                "message": (
                    "ticket_type='subtask' requires a parent_ticket_id "
                    "(the parent task this subtask belongs to)."
                ),
                "field": "parent_ticket_id",
            },
        )

    if this_ticket_id is not None and parent_ticket_id == this_ticket_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "self_parent",
                "message": "A ticket cannot be its own parent.",
                "field": "parent_ticket_id",
            },
        )

    parent = db.get(Ticket, parent_ticket_id)
    if parent is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "parent_not_found",
                "message": f"parent_ticket_id {parent_ticket_id} does not exist.",
                "field": "parent_ticket_id",
            },
        )
    if parent.project_id != project_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "parent_cross_project",
                "message": (
                    f"Parent ticket {parent.ticket_key} belongs to a different "
                    f"project. A subtask must share its parent's project."
                ),
                "field": "parent_ticket_id",
            },
        )
    if parent.ticket_type == TicketType.subtask:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "parent_is_subtask",
                "message": (
                    f"Parent ticket {parent.ticket_key} is itself a subtask. "
                    f"Sub-tasks are one level deep only (matching Jira)."
                ),
                "field": "parent_ticket_id",
            },
        )
    return parent


def create_ticket(db: Session, data: TicketCreate) -> Ticket:
    values = data.model_dump()

    # Validate project exists
    project = db.get(Project, values["project_id"])
    if not project:
        raise HTTPException(404, "Project not found")

    # DWB-332: Jira-disabled hard gate at create time.
    _raise_if_jira_disabled(project, values.get("jira_issue_key"))

    # DWB-455: validate sub-task parent linkage. Returns the parent Ticket
    # (subtasks) or None (everything else). Raises 400 on any rule violation.
    parent = _resolve_subtask_parent(
        db,
        ticket_type=values["ticket_type"],
        parent_ticket_id=values.get("parent_ticket_id"),
        project_id=values["project_id"],
    )

    # Auto-assign sprint_id if not provided. DWB-455: a subtask defaults to its
    # parent's sprint (keeping the Project->Epic->Sprint->Ticket chain valid)
    # rather than the project's active sprint.
    if values.get("sprint_id") is None:
        if parent is not None:
            sprint = db.get(Sprint, parent.sprint_id)
            values["sprint_id"] = parent.sprint_id
        else:
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

    # Epic assignment. DWB-455: a subtask always inherits its parent's epic_id
    # (overriding any supplied value); otherwise fall back to the sprint's epic.
    if parent is not None:
        values["epic_id"] = parent.epic_id
    elif values.get("epic_id") is None and sprint:
        values["epic_id"] = sprint.epic_id

    ticket = Ticket(**values)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def update_ticket(
    db: Session, ticket: Ticket, data: TicketUpdate, acting_agent_id: int | None = None
) -> Ticket:
    updates = data.model_dump(exclude_unset=True)
    old_status = ticket.status
    old_assigned = ticket.assigned_agent_id

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

    # DWB-455: sub-task linkage validation. Only runs when the update touches
    # ticket_type or parent_ticket_id; otherwise the existing pair is unchanged
    # and already-valid. Validates the RESULTING (type, parent) combination.
    if "ticket_type" in updates or "parent_ticket_id" in updates:
        new_type = updates.get("ticket_type", ticket.ticket_type)
        new_parent_id = updates.get("parent_ticket_id", ticket.parent_ticket_id)

        # Block converting a ticket that already has children into a subtask
        # (would create a two-level tree).
        if new_type == TicketType.subtask:
            has_children = db.scalar(
                select(Ticket.id)
                .where(Ticket.parent_ticket_id == ticket.id)
                .limit(1)
            )
            if has_children:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "has_children_cannot_be_subtask",
                        "message": (
                            f"Ticket {ticket.ticket_key} has sub-tasks and "
                            f"cannot itself become a subtask (one level only)."
                        ),
                        "field": "ticket_type",
                    },
                )

        parent = _resolve_subtask_parent(
            db,
            ticket_type=new_type,
            parent_ticket_id=new_parent_id,
            project_id=ticket.project_id,
            this_ticket_id=ticket.id,
        )
        # A subtask inherits its parent's epic so the hierarchy stays valid.
        if parent is not None:
            updates["epic_id"] = parent.epic_id

    status_changed = "status" in updates and updates["status"] != old_status

    for key, value in updates.items():
        setattr(ticket, key, value)

    # DWB-373: Stamp completed_at on transition INTO done so the sessions list
    # aggregator (filters on Ticket.completed_at in [opened_at, closed_at])
    # can count completions within a session window. The column existed since
    # day one but was only written by seed_demo; PATCH-to-done left it NULL,
    # so tickets_completed was always 0. Re-stamp on every done crossing so a
    # rework→done loop attributes to the later session that closed it.
    if status_changed and updates["status"] == TicketStatus.done:
        ticket.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(ticket)

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

    # DWB-409: emit semantic activity events on top of the middleware's
    # generic `updated` row. Distinct verbs per the no-double-log rule
    # (see services/activity_log.py). Actor = the X-Agent-ID-resolved
    # acting agent, falling back to the (now-current) assignee.
    _emit_ticket_events(db, ticket, old_status, old_assigned, updates, acting_agent_id)

    # DWB-425: auto-score the close (ticket_closed + no-rework bonus,
    # zero_token_close, forgot). Folded with commit=False then one commit.
    # Scoring is a side-effect: a failure here must never break the ticket
    # PATCH, so swallow + rollback the score writes only.
    if status_changed and updates.get("status") == TicketStatus.done:
        try:
            scoring_triggers.score_ticket_closed(db, ticket, commit=False)
            db.commit()
        except Exception as exc:
            logger.warning("Scoring on ticket close failed for %s: %s", ticket.id, exc)
            db.rollback()

    return ticket


def _emit_ticket_events(
    db: Session,
    ticket: Ticket,
    old_status: TicketStatus,
    old_assigned: int | None,
    updates: dict,
    acting_agent_id: int | None,
) -> None:
    """Emit semantic activity_log events for a ticket update (DWB-409).

    Verbs (all distinct from the middleware's created/updated/deleted):
    - status_changed: any status transition EXCEPT a rework reopen, details {from, to}
    - reopened: a done -> in_progress rework transition, details {from, to}. This
      REPLACES status_changed for that transition (one semantic row per event;
      reopened carries {from, to} so nothing is lost). Read-side dedup only
      collapses generic-vs-semantic, so emitting both semantic verbs would
      re-create the double-line problem (DWB-409 TL decision).
    - assigned: assigned_agent_id changed to a non-null agent,
      details {agent: <name>, agent_id: <id>}
    """
    actor_id = acting_agent_id or ticket.assigned_agent_id
    events: list[tuple[str, dict]] = []

    status_changed = "status" in updates and updates["status"] != old_status
    if status_changed:
        new_status = updates["status"]
        old_val = old_status.value if hasattr(old_status, "value") else str(old_status)
        new_val = new_status.value if hasattr(new_status, "value") else str(new_status)
        if old_status == TicketStatus.done and new_status == TicketStatus.in_progress:
            events.append(("reopened", {"from": old_val, "to": new_val}))
        else:
            events.append(("status_changed", {"from": old_val, "to": new_val}))

    new_assigned = updates.get("assigned_agent_id")
    if (
        "assigned_agent_id" in updates
        and new_assigned is not None
        and new_assigned != old_assigned
    ):
        assignee = db.get(Agent, new_assigned)
        events.append((
            "assigned",
            {"agent": assignee.name if assignee else None, "agent_id": new_assigned},
        ))

    if not events:
        return

    for action, details in events:
        log_activity(db, ticket.project_id, actor_id, "ticket", ticket.id, action, details)
    db.commit()


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

    rework_record = FailureRecord(
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
    )
    db.add(rework_record)
    db.flush()  # populate rework_record.id for the scoring ref

    db.add(Alert(
        project_id=ticket.project_id,
        raised_by_agent_id=pm_agent_id,
        ticket_id=ticket.id,
        title=f"Rework detected: {ticket.ticket_key}",
        body=f"{ticket.ticket_key} was moved back to in_progress after being marked done. A failure record has been created.",
        severity=AlertSeverity.info,
        status=AlertStatus.open,
    ))

    # DWB-425: penalize the rework, folded into this transaction. Side-effect
    # only - never let a scoring failure break rework detection.
    try:
        scoring_triggers.score_failure_record(db, rework_record, commit=False)
    except Exception as exc:
        logger.warning("Scoring rework failed for ticket %s: %s", ticket.id, exc)

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
    """Check for existing stale alert and create one if none exists. Returns {alert_created, alert_id}.

    DWB-388: dedup key is (ticket_id, alert_type=stale, open|acknowledged).
    The previous title-substring match included f"{minutes_stale}m", so the
    LiveSessions frontend sweeper's incrementing 10m/20m/30m thresholds bypassed
    dedup and produced one alert per 10-min hop (13 dupes seen on RVP-007).
    "stale" in the title acts as the type discriminator so this dedup does not
    accidentally swallow other ticket-bound alerts like rework notifications.
    """
    existing = db.scalars(
        select(Alert)
        .where(Alert.ticket_id == ticket.id)
        .where(Alert.status.in_([AlertStatus.open, AlertStatus.acknowledged]))
        .where(Alert.title.contains("stale"))
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

    # DWB-425: penalize the stale ticket once (idempotent per ticket). Side-
    # effect only - a scoring failure must not break stale alerting.
    try:
        scoring_triggers.score_stale(db, ticket, commit=True)
    except Exception as exc:
        logger.warning("Scoring stale failed for ticket %s: %s", ticket.id, exc)
        db.rollback()

    return {"alert_created": True, "alert_id": alert.id}


def delete_ticket(db: Session, ticket: Ticket) -> None:
    db.delete(ticket)
    db.commit()
