# Path: app/schemas/hook_session.py
# File: hook_session.py
# Created: 2026-04-09
# Purpose: Pydantic schemas for hook session endpoints and teammate registration
# Caller: app/routers/hooks.py
# Callees: pydantic
# Data In: JSON request body from Claude Code hooks and teammate registration
# Data Out: HookEventInput, RegisterAgentInput, DeregisterAgentInput, HookSessionRead
# Last Modified: 2026-04-16

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.hook_session import HookSessionStatus, HookSessionType


class HookEventInput(BaseModel):
    """Raw hook event data from Claude Code lifecycle hooks.

    Claude Code sends JSON via stdin to hook commands. The exact shape
    varies by event type, but these are the fields we care about.
    """
    session_id: str | None = None
    transcript_path: str | None = None
    cwd: str | None = None
    agent_name: str | None = None
    hook_event: str | None = None


class RegisterAgentInput(BaseModel):
    """Register a teammate as an active hook session."""
    project_id: int
    agent_id: int
    agent_name: str


class DeregisterAgentInput(BaseModel):
    """Deregister (complete) a teammate's active hook session."""
    project_id: int
    agent_id: int


class HookSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    transcript_path: str | None
    agent_id: int | None
    project_id: int
    ticket_id: int | None
    sprint_id: int | None
    start_time: datetime
    end_time: datetime | None
    total_tokens: int
    token_breakdown: dict | None
    status: HookSessionStatus
    session_type: HookSessionType
    agent_name: str | None
    hook_event: str | None
    created_at: datetime
