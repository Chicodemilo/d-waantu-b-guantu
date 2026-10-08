# Path: app/schemas/inter_agent_message.py
# File: inter_agent_message.py
# Created: 2026-06-24
# Purpose: Pydantic schemas for the inter-agent message capture hook (DWB-447)
#          and the project agent-message list endpoint (DWB-448)
# Caller: app/routers/hooks.py, app/routers/projects.py
# Callees: pydantic
# Data In: JSON request body from the SendMessage hook; DB rows for the list view
# Data Out: AgentMessageInput (request), InterAgentMessageRead (list row)
# Last Modified: 2026-10-08 (DWB-651: left permissive on purpose; the reason
#                and the caller are commented at the model)

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

    # DWB-651: DELIBERATELY PERMISSIVE - no extra="forbid" here.
    # CALLER: the PostToolUse SendMessage hook in `.claude/settings.json`. Today a
    # python one-liner there narrows the raw harness payload down to four keys
    # (to, message, summary, session_id), all declared below, so a forbid would
    # pass right now. It stays open anyway for two reasons: that filter lives in a
    # deployed settings file each cloning repo owns and may widen, and this
    # endpoint shares the same always-200 delivery-gap contract as the other hook
    # ingress points - a 422 loses the message row entirely and nothing reports it.
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
