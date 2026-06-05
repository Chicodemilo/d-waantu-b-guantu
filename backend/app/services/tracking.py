# Path: app/services/tracking.py
# File: tracking.py
# Created: 2026-03-30
# Purpose: Tracking service — start/stop events, token reports, overhead, time/token computation
# Caller: app/routers/tracking.py, app/services/ticket.py
# Callees: app/models/tracking_log.py, app/models/ticket.py
# Data In: db: Session, ticket_id, agent_id, tokens, source
# Data Out: TrackingLog, computed summaries
# Last Modified: 2026-06-05

"""Service layer for the tracking_log table — time and token event logging."""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.project import Project
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


def log_overhead_tokens(
    db: Session, project_id: int, agent_id: int, tokens: int, source: str = "hook"
) -> TrackingLog:
    """Insert an 'overhead_token_report' event AND atomically update the
    matching per-role bucket on the project row.

    Invariant (DWB-305): for every project,
        project.tl_overhead_tokens + project.pm_overhead_tokens
            == sum(tracking_log.tokens WHERE event_type='overhead_token_report')

    The row insert and the bucket increment commit together so future
    callers cannot drift the two apart. Classification: agents with
    role=='pm' land in pm_overhead_tokens; every other role (including the
    unusual case of a worker session that ended without ticket attribution)
    lands in tl_overhead_tokens so the invariant holds.
    """
    entry = TrackingLog(
        ticket_id=None,
        agent_id=agent_id,
        project_id=project_id,
        sprint_id=None,
        event_type="overhead_token_report",
        tokens=tokens,
        source=source,
    )
    db.add(entry)

    # Atomic bucket update — drift-proof by construction.
    project = db.get(Project, project_id)
    agent = db.get(Agent, agent_id) if agent_id else None
    if project is not None and tokens:
        if agent is not None and agent.role == "pm":
            project.pm_overhead_tokens += tokens
        else:
            project.tl_overhead_tokens += tokens

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


def compute_overhead_tokens(db: Session, project_id: int) -> int:
    """Sum tokens from overhead_token_report events for a project."""
    total = db.scalar(
        select(func.coalesce(func.sum(TrackingLog.tokens), 0))
        .where(TrackingLog.project_id == project_id)
        .where(TrackingLog.event_type == "overhead_token_report")
    )
    return total or 0


def get_project_summary(db: Session, project_id: int) -> dict:
    """Build a full tracking summary for a project."""

    # Per-ticket summary
    ticket_rows = db.execute(
        select(
            TrackingLog.ticket_id,
            Ticket.ticket_key,
            Ticket.title.label("ticket_title"),
            Ticket.assigned_agent_id,
            TrackingLog.agent_id,
            Agent.name.label("agent_name"),
            Agent.role.label("agent_role"),
        )
        .join(Ticket, TrackingLog.ticket_id == Ticket.id)
        .join(Agent, TrackingLog.agent_id == Agent.id)
        .where(TrackingLog.project_id == project_id)
        .where(TrackingLog.ticket_id.isnot(None))
        .group_by(TrackingLog.ticket_id, Ticket.ticket_key, Ticket.title, Ticket.assigned_agent_id, TrackingLog.agent_id, Agent.name, Agent.role)
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
            "title": row.ticket_title,
            "assigned_agent_id": row.assigned_agent_id,
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
        # DWB-306: per_agent must aggregate BOTH ticket-attributed token_report
        # events AND overhead_token_report events. Previously this filter only
        # included 'token_report', so any agent in an overhead role (PM, TL)
        # rolled up as 0 tokens even when their overhead attribution was
        # correct at project_total.overhead_tokens.
        agent_ticket_tokens = db.scalar(
            select(func.coalesce(func.sum(TrackingLog.tokens), 0))
            .where(TrackingLog.project_id == project_id)
            .where(TrackingLog.agent_id == row.agent_id)
            .where(TrackingLog.event_type == "token_report")
        ) or 0
        agent_overhead_tokens = db.scalar(
            select(func.coalesce(func.sum(TrackingLog.tokens), 0))
            .where(TrackingLog.project_id == project_id)
            .where(TrackingLog.agent_id == row.agent_id)
            .where(TrackingLog.event_type == "overhead_token_report")
        ) or 0
        per_agent.append({
            "agent_id": row.agent_id,
            "name": row.name,
            "role": row.role,
            "time_seconds": agent_time,
            # `tokens` is the total across ticket + overhead attribution so
            # dashboards see a correct headline number for every agent.
            # `overhead_tokens` is the breakdown of the overhead portion.
            "tokens": agent_ticket_tokens + agent_overhead_tokens,
            "overhead_tokens": agent_overhead_tokens,
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
    overhead_tokens = compute_overhead_tokens(db, project_id)

    return {
        "per_ticket": per_ticket,
        "per_agent": per_agent,
        "per_sprint": per_sprint,
        "project_total": {
            "time_seconds": total_time,
            "tokens": total_tokens,
            "overhead_time_seconds": overhead_time,
            "overhead_tokens": overhead_tokens,
        },
    }
