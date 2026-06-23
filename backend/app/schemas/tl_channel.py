# Path: app/schemas/tl_channel.py
# File: tl_channel.py
# Created: 2026-06-23
# Purpose: Pydantic schemas for the cross-project team-lead channel API (DWB-436/437) - send request, channel message (read-state aware), unread + mark-read responses.
# Caller: app/routers/tl_channel.py
# Callees: pydantic
# Data In: service dicts from app.services.tl_channel, send/mark-read request bodies
# Data Out: TlMessageCreate, TlChannelMessage, TlChannelList, MarkReadRequest, MarkReadResponse, SendResponse
# Last Modified: 2026-06-23

from pydantic import BaseModel


class TlMessageCreate(BaseModel):
    """Send a message into the team-lead channel (DWB-437).

    ``to_agent_id`` omitted/None => BROADCAST to every other team-lead.
    Sender and any named recipient must both be role=team-lead (enforced
    server-side, 400 otherwise).
    """
    from_agent_id: int
    to_agent_id: int | None = None
    body: str


class ReadReceipt(BaseModel):
    """One team-lead's read receipt for a channel message."""
    agent_id: int
    agent_name: str | None
    read_at: str | None


class TlChannelMessage(BaseModel):
    """One channel message as the UI / unread surfacing sees it.

    DIRECT vs BROADCAST: ``is_broadcast`` is True exactly when ``to_agent_id``
    is null. Read-state is the full ``read_by`` roster of who has read it
    (DWB-437 contract): each entry is {agent_id, agent_name, read_at}. The
    client derives its own read flag (is my id in read_by). ``read_by_count`` is
    a convenience mirror of ``len(read_by)`` (no per-viewer fields are sent).
    """
    id: int
    from_agent_id: int
    from_agent_name: str | None
    from_project_id: int
    from_project_prefix: str | None
    to_agent_id: int | None
    to_agent_name: str | None
    is_broadcast: bool
    body: str
    created_at: str | None
    read_by: list[ReadReceipt]
    read_by_count: int


class MarkReadRequest(BaseModel):
    """Mark channel messages read for an agent (DWB-437).

    Provide ``message_id`` to mark one, or ``all: true`` to mark every message
    currently addressed-to / visible-to the agent as read. Exactly one mode.
    """
    agent_id: int
    message_id: int | None = None
    all: bool = False


class MarkReadResponse(BaseModel):
    status: str
    agent_id: int
    marked: int


class SendResponse(BaseModel):
    """Result of a send: the created message plus how many team-leads were
    pinged via an alert (1 for a direct send, one per OTHER team-lead for a
    broadcast)."""
    status: str
    message: TlChannelMessage
    alert_count: int
