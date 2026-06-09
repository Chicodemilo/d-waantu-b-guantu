# Path: app/schemas/dwb_session.py
# File: dwb_session.py
# Created: 2026-06-09
# Purpose: Pydantic schemas for DWB session CRUD (DWB-335)
# Caller: app/routers/dwb_sessions.py (DWB-338)
# Callees: pydantic
# Data In: JSON request body
# Data Out: DwbSessionCreate, DwbSessionUpdate, DwbSessionRead
# Last Modified: 2026-06-09

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.dwb_session import DwbCloseMethod, DwbCloseReason, DwbOpenMethod


class DwbSessionCreate(BaseModel):
    """Open a new DWB session. closed_at is always NULL on create — close is
    a separate update flow. open_method is required; the caller signals
    whether the open was a clean regex match, an AI-confident call, or an
    AI-asked confirmation."""

    project_id: int
    opened_at: datetime
    open_method: DwbOpenMethod
    open_phrase: str | None = None


class DwbSessionUpdate(BaseModel):
    """Close (or amend) an open DWB session. Fields are all optional so the
    same schema covers explicit close (closed_at + close_method + close_reason
    + close_phrase) and the idle sweeper's close (closed_at + close_method=
    idle_timeout + close_reason=idle, no phrase)."""

    closed_at: datetime | None = None
    close_phrase: str | None = None
    close_method: DwbCloseMethod | None = None
    close_reason: DwbCloseReason | None = None
    total_tokens: int | None = None
    total_time_seconds: int | None = None


class DwbSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    opened_at: datetime
    closed_at: datetime | None
    open_phrase: str | None
    close_phrase: str | None
    open_method: DwbOpenMethod
    close_method: DwbCloseMethod | None
    close_reason: DwbCloseReason | None
    total_tokens: int
    total_time_seconds: int
    is_open: int | None
    created_at: datetime
    updated_at: datetime
