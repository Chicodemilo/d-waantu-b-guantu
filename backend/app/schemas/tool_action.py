# Path: app/schemas/tool_action.py
# File: tool_action.py
# Created: 2026-06-22
# Purpose: Pydantic schemas for the PostToolUse + lifecycle hook tool-action endpoints (DWB-417, DWB-421)
# Caller: app/routers/hooks.py
# Callees: pydantic
# Data In: JSON request body from the Claude Code PostToolUse / Notification / PreCompact hooks
# Data Out: ToolUseInput, LifecycleEventInput (requests), ToolActionRead (response)
# Last Modified: 2026-06-22 (DWB-421: LifecycleEventInput)

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ToolUseInput(BaseModel):
    """Raw PostToolUse hook payload from Claude Code.

    Claude Code fires PostToolUse after every tool call and includes the
    session_id, the tool name, and the tool input. All fields are optional so
    the handler degrades gracefully (delivery-gap tolerance): a missing or
    unresolvable session_id still persists a row with null context rather than
    erroring, and the endpoint always returns 200.

    ``tool_input`` is ingested but NOT persisted on this foundation ticket; the
    sibling tickets derive ``target`` / ``tool_metadata`` from it per tool type.
    """

    session_id: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    cwd: str | None = None
    hook_event_name: str | None = None


class LifecycleEventInput(BaseModel):
    """Raw Notification / PreCompact lifecycle hook payload from Claude Code
    (DWB-421).

    These are not tool calls, so they reuse the tool_actions table with a
    lifecycle event_type. ``hook_event_name`` selects the branch:
      Notification -> persists target = ``message``
      PreCompact   -> persists target = ``trigger`` (manual / auto)

    All fields optional for the same delivery-gap tolerance as the tool-use
    endpoint: a missing/unresolvable session_id still persists a row with null
    context, and the endpoint always returns 200.
    """

    session_id: str | None = None
    cwd: str | None = None
    hook_event_name: str | None = None
    # Notification-specific: the notification message / reason.
    message: str | None = None
    # PreCompact-specific: the compaction trigger (manual / auto).
    trigger: str | None = None


class ToolActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int | None
    session_id: str | None
    dwb_session_id: int | None
    ticket_id: int | None
    tool_name: str
    target: str | None
    event_type: str
    tool_metadata: dict | None
    created_at: datetime
