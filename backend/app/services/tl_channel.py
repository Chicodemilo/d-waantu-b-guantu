# Path: app/services/tl_channel.py
# File: tl_channel.py
# Created: 2026-06-23
# Purpose: Cross-project team-lead channel service (DWB-437) - send (direct/broadcast) with role guard + alert ping, list the whole channel with per-viewer read-state, list/mark unread, mark-read. NOT project-scoped.
# Caller: app/routers/tl_channel.py, app/services/agent_memory.py (DWB-438 unread surfacing)
# Callees: app/models/tl_message.py, app/models/agent.py, app/models/project.py, app/models/alert.py
# Data In: db: Session, agents/ids, message body
# Data Out: TlMessage, serialized channel-message dicts, counts
# Last Modified: 2026-06-23

"""The "Archie Channel" (DWB-437).

Team-leads (one per project) message each other across projects. A message is
DIRECT (``to_agent_id`` set) or BROADCAST (``to_agent_id`` NULL = every other
team-lead). Every team-lead SEES every message; addressing only governs the
unread ping. A direct send pings the one target; a broadcast pings every OTHER
team-lead. Pings reuse the alerts table (per-agent ``recipient_agent_id``).
"""

import logging

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.project import Project
from app.models.tl_message import TlMessage, TlMessageRead

logger = logging.getLogger(__name__)

# Chars of the message body echoed into a ping alert.
_PING_BODY_MAX = 160

_TEAM_LEAD_ROLES = ("team-lead", "team_lead")


def is_team_lead(agent: Agent) -> bool:
    """True when an agent holds the team-lead role (either spelling)."""
    return agent.role in _TEAM_LEAD_ROLES


# ---------------------------------------------------------------------------
# Team-lead lookups (cross-project)
# ---------------------------------------------------------------------------


def _team_lead_ids(db: Session, exclude_agent_id: int | None = None) -> list[int]:
    """All active team-lead agent ids across every project (the channel is
    cross-project). Optionally exclude one agent (e.g. the broadcast sender)."""
    stmt = (
        select(Agent.id)
        .where(Agent.role.in_(_TEAM_LEAD_ROLES))
        .where(Agent.is_active.is_(True))
    )
    if exclude_agent_id is not None:
        stmt = stmt.where(Agent.id != exclude_agent_id)
    return list(db.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


def send_message(
    db: Session,
    *,
    from_agent: Agent,
    to_agent: Agent | None,
    body: str,
) -> tuple[TlMessage, int]:
    """Persist a channel message and ping the recipient(s) via alerts.

    Role guard is enforced by the router before this is called; we assert it
    here too as defense-in-depth. Returns (message, alert_count). Direct ->
    1 alert (the target); broadcast -> 1 per OTHER team-lead. Caller owns the
    commit boundary (the router uses get_db's session lifecycle).
    """
    if not is_team_lead(from_agent):
        raise HTTPException(400, "sender must be a team-lead")
    if to_agent is not None and not is_team_lead(to_agent):
        raise HTTPException(400, "recipient must be a team-lead")
    if from_agent.project_id is None:
        # from_project_id is NOT NULL; a team-lead always has a home project.
        raise HTTPException(400, "sender has no home project")
    body = (body or "").strip()
    if not body:
        raise HTTPException(400, "message body must not be empty")

    msg = TlMessage(
        from_agent_id=from_agent.id,
        to_agent_id=to_agent.id if to_agent is not None else None,
        from_project_id=from_agent.project_id,
        body=body,
    )
    db.add(msg)
    db.flush()

    alert_count = _ping(db, msg, from_agent, to_agent)
    db.commit()
    db.refresh(msg)
    logger.info(
        "tl-channel send #%s from %s -> %s (%s alerts)",
        msg.id, from_agent.name,
        to_agent.name if to_agent else "ALL", alert_count,
    )
    return msg, alert_count


def _ping(
    db: Session, msg: TlMessage, from_agent: Agent, to_agent: Agent | None
) -> int:
    """Write per-agent alert rows for a channel message. Guarded so a ping
    failure never loses the message."""
    snippet = msg.body[:_PING_BODY_MAX]
    try:
        if to_agent is not None:
            recipients = [to_agent.id]
            title = f"TL message from {from_agent.name}"
            body = f"{from_agent.name} sent you a team-lead message: {snippet}"
        else:
            recipients = _team_lead_ids(db, exclude_agent_id=from_agent.id)
            title = f"{from_agent.name} broadcast to all team-leads"
            body = f"{from_agent.name} broadcast to all team-leads: {snippet}"

        count = 0
        for rid in recipients:
            recipient = db.get(Agent, rid)
            # Surface the alert on the recipient's own project board; fall back
            # to the sender's project if the recipient has no home project.
            pid = (
                recipient.project_id
                if recipient and recipient.project_id is not None
                else from_agent.project_id
            )
            db.add(Alert(
                project_id=pid,
                raised_by_agent_id=from_agent.id,
                recipient_agent_id=rid,
                title=title,
                body=body,
                severity=AlertSeverity.info,
                status=AlertStatus.open,
            ))
            count += 1
        db.flush()
        return count
    except Exception:
        logger.warning("tl-channel ping failed for message %s", msg.id, exc_info=True)
        return 0


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------


def _read_by_map(db: Session, message_ids: list[int]) -> dict[int, list[dict]]:
    """message_id -> [{agent_id, agent_name, read_at}] read roster (DWB-437),
    ordered by read time. Resolves reader names in the same pass."""
    if not message_ids:
        return {}
    rows = db.execute(
        select(
            TlMessageRead.message_id,
            TlMessageRead.agent_id,
            Agent.name,
            TlMessageRead.read_at,
        )
        .outerjoin(Agent, Agent.id == TlMessageRead.agent_id)
        .where(TlMessageRead.message_id.in_(message_ids))
        .order_by(TlMessageRead.read_at.asc())
    ).all()
    out: dict[int, list[dict]] = {}
    for mid, aid, name, read_at in rows:
        out.setdefault(mid, []).append({
            "agent_id": aid,
            "agent_name": name,
            "read_at": read_at.isoformat() if read_at else None,
        })
    return out


def _serialize_rows(db: Session, rows) -> list[dict]:
    """Turn ORM TlMessage rows into the TlChannelMessage dict shape, resolving
    sender/recipient names + sender project prefix and the read_by roster."""
    rows = list(rows)
    if not rows:
        return []
    ids = [m.id for m in rows]
    read_by = _read_by_map(db, ids)

    # Resolve names/prefixes in bulk.
    agent_ids = {m.from_agent_id for m in rows} | {
        m.to_agent_id for m in rows if m.to_agent_id is not None
    }
    project_ids = {m.from_project_id for m in rows}
    names = dict(db.execute(
        select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
    ).all()) if agent_ids else {}
    prefixes = dict(db.execute(
        select(Project.id, Project.prefix).where(Project.id.in_(project_ids))
    ).all()) if project_ids else {}

    out: list[dict] = []
    for m in rows:
        roster = read_by.get(m.id, [])
        out.append({
            "id": m.id,
            "from_agent_id": m.from_agent_id,
            "from_agent_name": names.get(m.from_agent_id),
            "from_project_id": m.from_project_id,
            "from_project_prefix": prefixes.get(m.from_project_id),
            "to_agent_id": m.to_agent_id,
            "to_agent_name": names.get(m.to_agent_id) if m.to_agent_id else None,
            "is_broadcast": m.to_agent_id is None,
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "read_by": roster,
            "read_by_count": len(roster),
        })
    return out


def serialize_message(db: Session, msg: TlMessage) -> dict:
    """Serialize a single message into the TlChannelMessage dict shape."""
    return _serialize_rows(db, [msg])[0]


def list_channel(db: Session, limit: int = 200) -> list[dict]:
    """The whole channel, most-recent-first, across all projects. Each message
    carries the full ``read_by`` roster; the client derives its own read flag."""
    rows = db.scalars(
        select(TlMessage)
        .order_by(TlMessage.created_at.desc(), TlMessage.id.desc())
        .limit(limit)
    ).all()
    return _serialize_rows(db, rows)


def _unread_stmt(agent_id: int):
    """Messages addressed-to / visible-to an agent that they have NOT read:
    broadcasts (to_agent_id NULL) + directs to them, excluding their own sends,
    minus any with a read receipt by them."""
    read_subq = (
        select(TlMessageRead.message_id)
        .where(TlMessageRead.agent_id == agent_id)
    )
    return (
        select(TlMessage)
        .where(
            or_(TlMessage.to_agent_id == agent_id, TlMessage.to_agent_id.is_(None))
        )
        .where(TlMessage.from_agent_id != agent_id)
        .where(TlMessage.id.notin_(read_subq))
        .order_by(TlMessage.created_at.desc(), TlMessage.id.desc())
    )


def unread_for_agent(db: Session, agent_id: int) -> list[dict]:
    """Unread channel messages for an agent (broadcasts + directs-to-agent not
    yet read). Serialized with read=False for the viewer."""
    rows = db.scalars(_unread_stmt(agent_id)).all()
    return _serialize_rows(db, rows)


def mark_read(
    db: Session,
    *,
    agent_id: int,
    message_id: int | None = None,
    mark_all: bool = False,
) -> int:
    """Record read receipts for an agent. With ``message_id`` marks that one
    message; with ``mark_all`` marks every currently-unread (visible) message.
    Idempotent: an already-read message is not re-inserted. Returns the number
    of NEW receipts written. Caller owns the commit."""
    if mark_all:
        target_ids = [m.id for m in db.scalars(_unread_stmt(agent_id)).all()]
    elif message_id is not None:
        if db.get(TlMessage, message_id) is None:
            raise HTTPException(404, f"message {message_id} not found")
        # Skip if already read.
        already = db.get(TlMessageRead, (message_id, agent_id))
        target_ids = [] if already else [message_id]
    else:
        raise HTTPException(400, "provide message_id or all=true")

    marked = 0
    for mid in target_ids:
        if db.get(TlMessageRead, (mid, agent_id)) is not None:
            continue
        db.add(TlMessageRead(message_id=mid, agent_id=agent_id))
        marked += 1
    if marked:
        db.flush()
    return marked
