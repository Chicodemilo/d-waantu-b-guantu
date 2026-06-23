# Path: app/routers/tl_channel.py
# File: tl_channel.py
# Created: 2026-06-23
# Purpose: HTTP API for the cross-project team-lead channel (DWB-437) - send (role-guarded, with alert ping), list whole channel with read-state, list unread per agent, mark-read.
# Caller: app/main.py
# Callees: app/services/tl_channel.py, app/models/agent.py
# Data In: HTTP GET/POST
# Data Out: TlChannelMessage[], SendResponse, MarkReadResponse
# Last Modified: 2026-06-23

"""Team-lead channel API (DWB-437). All routes under /api/tl-channel."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.schemas.tl_channel import (
    MarkReadRequest,
    MarkReadResponse,
    SendResponse,
    TlChannelMessage,
    TlMessageCreate,
)
from app.services import tl_channel as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tl-channel", tags=["tl-channel"])


@router.get("", response_model=list[TlChannelMessage])
def list_channel(
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """The whole channel, most-recent-first, across all projects. Every
    team-lead sees every message; each carries the full ``read_by`` roster so
    the client derives its own read flag (is my id in read_by)."""
    return svc.list_channel(db, limit=limit)


@router.get("/unread", response_model=list[TlChannelMessage])
def list_unread(
    agent_id: int = Query(..., description="The team-lead checking their unread"),
    db: Session = Depends(get_db),
):
    """Unread messages addressed to / visible to an agent (broadcasts + directs
    to them, excluding their own sends, minus anything already read)."""
    if db.get(Agent, agent_id) is None:
        raise HTTPException(404, f"Agent not found: {agent_id}")
    return svc.unread_for_agent(db, agent_id)


@router.post("", response_model=SendResponse, status_code=201)
def send_message(data: TlMessageCreate, db: Session = Depends(get_db)):
    """Send a channel message. ``to_agent_id`` omitted => broadcast to all other
    team-leads. ROLE GUARD: the sender AND any named recipient must be
    role=team-lead, else 400. Pings the recipient(s) via per-agent alerts."""
    sender = db.get(Agent, data.from_agent_id)
    if sender is None:
        raise HTTPException(404, f"Sender agent not found: {data.from_agent_id}")
    if not svc.is_team_lead(sender):
        logger.warning("tl-channel send rejected: %s is not a team-lead", sender.name)
        raise HTTPException(
            400, f"Agent {sender.name!r} is not a team-lead; only team-leads use the channel"
        )

    recipient = None
    if data.to_agent_id is not None:
        recipient = db.get(Agent, data.to_agent_id)
        if recipient is None:
            raise HTTPException(404, f"Recipient agent not found: {data.to_agent_id}")
        if not svc.is_team_lead(recipient):
            logger.warning(
                "tl-channel send rejected: recipient %s is not a team-lead", recipient.name
            )
            raise HTTPException(
                400,
                f"Agent {recipient.name!r} is not a team-lead; channel messages "
                "can only be addressed to a team-lead",
            )

    msg, alert_count = svc.send_message(
        db, from_agent=sender, to_agent=recipient, body=data.body
    )
    message = svc.serialize_message(db, msg)
    return {"status": "ok", "message": message, "alert_count": alert_count}


@router.post("/mark-read", response_model=MarkReadResponse)
def mark_read(data: MarkReadRequest, db: Session = Depends(get_db)):
    """Mark channel messages read for an agent: one (``message_id``) or every
    currently-unread one (``all: true``). Idempotent."""
    if db.get(Agent, data.agent_id) is None:
        raise HTTPException(404, f"Agent not found: {data.agent_id}")
    marked = svc.mark_read(
        db,
        agent_id=data.agent_id,
        message_id=data.message_id,
        mark_all=data.all,
    )
    db.commit()
    return {"status": "ok", "agent_id": data.agent_id, "marked": marked}
