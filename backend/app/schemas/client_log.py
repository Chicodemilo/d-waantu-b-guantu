# Path: app/schemas/client_log.py
# File: client_log.py
# Created: 2026-06-10
# Purpose: Pydantic schemas for client_logs (DWB-371) - lenient batch input, structured output
# Caller: app/routers/client_logs.py
# Callees: pydantic, app/models/client_log
# Data In: HTTP body dicts, ORM rows
# Data Out: ClientLogCreate, ClientLogRead, ClientLogBatchResponse
# Last Modified: 2026-06-10

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.client_log import ClientLogLevel


class ClientLogCreate(BaseModel):
    """Single client log record. Validation is intentionally light - the
    service drops malformed records individually rather than rejecting
    the whole batch, so a buggy frontend can't silently lose every
    log line until someone fixes the schema."""

    level: ClientLogLevel
    category: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1)
    occurred_at: datetime
    route: str | None = Field(None, max_length=500)
    context_json: dict[str, Any] | None = None
    source: str = Field("frontend", max_length=32)


class ClientLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    level: ClientLogLevel
    category: str
    message: str
    context_json: dict[str, Any] | None = None
    route: str | None = None
    occurred_at: datetime
    created_at: datetime


class ClientLogBatchResponse(BaseModel):
    received: int
    accepted: int
    rejected: int
    # When records are rejected, surface the index + reason so the
    # frontend can repair its emitter rather than silently losing logs.
    rejections: list[dict[str, Any]] = []
    trimmed: int = 0  # rows dropped by retention enforcement
