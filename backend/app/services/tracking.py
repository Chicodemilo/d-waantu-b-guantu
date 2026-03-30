# Path: app/services/tracking.py
# File: tracking.py
# Created: 2026-03-30
# Purpose: Tracking service — start/stop events, token reports, overhead, time/token computation
# Caller: app/routers/tracking.py, app/services/ticket.py
# Callees: app/models/tracking_log.py, app/models/ticket.py
# Data In: db: Session, ticket_id, agent_id, tokens, source
# Data Out: TrackingLog, computed summaries
# Last Modified: 2026-03-30

"""Service layer for the tracking_log table — time and token event logging."""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.sprint import Sprint
from app.models.ticket import Ticket
from app.models.tracking_log import TrackingLog


def log_start(db: Session, ticket_id: int, agent_id: int) -> TrackingLog:
    """Insert a 'start' event for a ticket."""
    ticket = db.get(Ticket, ticket_id)
    entry = TrackingLog(
        ticket_id=ticket_id,
        agent_id=agent_id,
        project_id=ticket.project_id,
        sprint_id=ticket.sprint_id,
        event_type="start",
        source="auto",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_stop(db: Session, ticket_id: int, agent_id: int) -> TrackingLog:
    """Insert a 'stop' event for a ticket."""
    ticket = db.get(Ticket, ticket_id)
    entry = TrackingLog(
        ticket_id=ticket_id,
        agent_id=agent_id,
        project_id=ticket.project_id,
        sprint_id=ticket.sprint_id,
        event_type="stop",
        source="auto",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_tokens(
    db: Session, ticket_id: int, agent_id: int, tokens: int, source: str = "manual"
) -> TrackingLog:
    """Insert a 'token_report' event for a ticket."""
    ticket = db.get(Ticket, ticket_id)
    entry = TrackingLog(
        ticket_id=ticket_id,
        agent_id=agent_id,
        project_id=ticket.project_id,
        sprint_id=ticket.sprint_id,
        event_type="token_report",
        tokens=tokens,
        source=source,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_overhead_start(db: Session, project_id: int, agent_id: int) -> TrackingLog:
    """Insert an 'overhead_start' event (no ticket)."""
    entry = TrackingLog(
        ticket_id=None,
        agent_id=agent_id,
        project_id=project_id,
        sprint_id=None,
        event_type="overhead_start",
        source="auto",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_overhead_stop(db: Session, project_id: int, agent_id: int) -> TrackingLog:
    """Insert an 'overhead_stop' event (no ticket)."""
    entry = TrackingLog(
        ticket_id=None,
        agent_id=agent_id,
        project_id=project_id,
        sprint_id=None,
        event_type="overhead_stop",
        source="auto",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def compute_ticket_time(db: Session, ticket_id: int) -> int:
    """Sum time between start/stop pairs for a ticket. Returns total seconds."""
    events = list(db.scalars(
        select(TrackingLog)
        .where(TrackingLog.ticket_id == ticket_id)
        .where(TrackingLog.event_type.in_(["start", "stop"]))
        .order_by(TrackingLog.timestamp.asc())
    ).all())

    total_seconds = 0
    start_time = None
    for e in events:
        if e.event_type == "start":
            start_time = e.timestamp
        elif e.event_type == "stop" and start_time is not None:
            total_seconds += int((e.timestamp - start_time).total_seconds())
            start_time = None

    return total_seconds


def compute_ticket_tokens(db: Session, ticket_id: int) -> int:
    """Sum all token_report events for a ticket."""
    total = db.scalar(
        select(func.coalesce(func.sum(TrackingLog.tokens), 0))
        .where(TrackingLog.ticket_id == ticket_id)
        .where(TrackingLog.event_type == "token_report")
    )
    return total or 0


def compute_overhead_time(db: Session, project_id: int) -> int:
    """Sum time between overhead_start/overhead_stop pairs for a project."""
    events = list(db.scalars(
        select(TrackingLog)
        .where(TrackingLog.project_id == project_id)
        .where(TrackingLog.event_type.in_(["overhead_start", "overhead_stop"]))
        .order_by(TrackingLog.timestamp.asc())
    ).all())

    total_seconds = 0
    start_time = None
    for e in events:
        if e.event_type == "overhead_start":
            start_time = e.timestamp
        elif e.event_type == "overhead_stop" and start_time is not None:
            total_seconds += int((e.timestamp - start_time).total_seconds())
            start_time = None

    return total_seconds


def get_project_summary(db: Session, project_id: int) -> dict:
    """Build a full tracking summary for a project."""

    # Per-ticket summary
    ticket_rows = db.execute(
        select(
            TrackingLog.ticket_id,
            Ticket.ticket_key,
            TrackingLog.agent_id,
            Agent.name.label("agent_name"),
            Agent.role.label("agent_role"),
        )
        .join(Ticket, TrackingLog.ticket_id == Ticket.id)
        .join(Agent, TrackingLog.agent_id == Agent.id)
        .where(TrackingLog.project_id == project_id)
        .where(TrackingLog.ticket_id.isnot(None))
        .group_by(TrackingLog.ticket_id, Ticket.ticket_key, TrackingLog.agent_id, Agent.name, Agent.role)
    ).all()

    per_ticket = []
    seen_tickets = set()
    for row in ticket_rows:
        if row.ticket_id in seen_tickets:
            continue
        seen_tickets.add(row.ticket_id)
        time_s = compute_ticket_time(db, row.ticket_id)
        tokens = compute_ticket_tokens(db, row.ticket_id)
        per_ticket.append({
            "ticket_id": row.ticket_id,
            "ticket_key": row.ticket_key,
            "time_seconds": time_s,
            "tokens": tokens,
            "agent": row.agent_name,
        })

    # Per-agent summary
    agent_rows = db.execute(
        select(
            TrackingLog.agent_id,
            Agent.name,
            Agent.role,
        )
        .join(Agent, TrackingLog.agent_id == Agent.id)
        .where(TrackingLog.project_id == project_id)
        .group_by(TrackingLog.agent_id, Agent.name, Agent.role)
    ).all()

    per_agent = []
    for row in agent_rows:
        # Time: sum of ticket time for this agent's tickets
        agent_ticket_ids = list(db.scalars(
            select(TrackingLog.ticket_id)
            .where(TrackingLog.project_id == project_id)
            .where(TrackingLog.agent_id == row.agent_id)
            .where(TrackingLog.ticket_id.isnot(None))
            .group_by(TrackingLog.ticket_id)
        ).all())
        agent_time = sum(compute_ticket_time(db, tid) for tid in agent_ticket_ids)
        agent_tokens = db.scalar(
            select(func.coalesce(func.sum(TrackingLog.tokens), 0))
            .where(TrackingLog.project_id == project_id)
            .where(TrackingLog.agent_id == row.agent_id)
            .where(TrackingLog.event_type == "token_report")
        ) or 0
        per_agent.append({
            "agent_id": row.agent_id,
            "name": row.name,
            "role": row.role,
            "time_seconds": agent_time,
            "tokens": agent_tokens,
        })

    # Per-sprint summary
    sprint_rows = db.execute(
        select(
            TrackingLog.sprint_id,
            Sprint.name.label("sprint_name"),
        )
        .join(Sprint, TrackingLog.sprint_id == Sprint.id)
        .where(TrackingLog.project_id == project_id)
        .where(TrackingLog.sprint_id.isnot(None))
        .group_by(TrackingLog.sprint_id, Sprint.name)
    ).all()

    per_sprint = []
    for row in sprint_rows:
        sprint_ticket_ids = list(db.scalars(
            select(TrackingLog.ticket_id)
            .where(TrackingLog.sprint_id == row.sprint_id)
            .where(TrackingLog.ticket_id.isnot(None))
            .group_by(TrackingLog.ticket_id)
        ).all())
        sprint_time = sum(compute_ticket_time(db, tid) for tid in sprint_ticket_ids)
        sprint_tokens = db.scalar(
            select(func.coalesce(func.sum(TrackingLog.tokens), 0))
            .where(TrackingLog.sprint_id == row.sprint_id)
            .where(TrackingLog.event_type == "token_report")
        ) or 0
        per_sprint.append({
            "sprint_id": row.sprint_id,
            "name": row.sprint_name,
            "time_seconds": sprint_time,
            "tokens": sprint_tokens,
        })

    # Project totals
    total_time = sum(t["time_seconds"] for t in per_ticket)
    total_tokens = db.scalar(
        select(func.coalesce(func.sum(TrackingLog.tokens), 0))
        .where(TrackingLog.project_id == project_id)
        .where(TrackingLog.event_type == "token_report")
    ) or 0
    overhead_time = compute_overhead_time(db, project_id)

    return {
        "per_ticket": per_ticket,
        "per_agent": per_agent,
        "per_sprint": per_sprint,
        "project_total": {
            "time_seconds": total_time,
            "tokens": total_tokens,
            "overhead_time_seconds": overhead_time,
        },
    }
