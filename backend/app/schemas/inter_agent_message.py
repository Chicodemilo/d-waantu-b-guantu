# Path: app/schemas/inter_agent_message.py
# File: inter_agent_message.py
# Created: 2026-06-24
# Purpose: Pydantic schemas for the inter-agent message capture hook (DWB-447)
#          and the project agent-message list endpoint (DWB-448)
# Caller: app/routers/hooks.py, app/routers/projects.py
# Callees: pydantic
# Data In: JSON request body from the SendMessage hook; DB rows for the list view
# Data Out: AgentMessageInput (request), InterAgentMessageRead (list row)
# Last Modified: 2026-06-24

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentMessageInput(BaseModel):
    """Raw SendMessage hook payload (DWB-447).

    The hook fires when one agent messages another. ``session_id`` identifies
    the SENDER's Claude Code session; the sender agent is resolved from it the
    same way token attribution resolves a session. All fields optional for the
    same delivery-gap tolerance as the other hooks: the endpoint always returns
    200, and an unresolvable session_id / project simply stores nothing.

    Agent message bodies ARE stored (they are not user text).
    """

    to: str | None = None
    message: str | None = None
    summary: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    hook_event_name: str | None = None


class InterAgentMessageRead(BaseModel):
    """One row of the project agent-message log (DWB-448)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_agent_id: int | None = None
    from_agent_name: str | None = None
    to_agent_id: int | None = None
    to_agent_name: str | None = None
    body: str
    summary: str | None = None
    created_at: datetime
    dwb_session_id: int | None = None
