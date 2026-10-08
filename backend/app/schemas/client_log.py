# Path: app/schemas/client_log.py
# File: client_log.py
# Created: 2026-06-10
# Purpose: Pydantic schemas for client_logs (DWB-371) - lenient batch input, structured output
# Caller: app/routers/client_logs.py
# Callees: pydantic, app/models/client_log
# Data In: HTTP body dicts, ORM rows
# Data Out: ClientLogCreate, ClientLogRead, ClientLogBatchResponse
# Last Modified: 2026-10-08 (DWB-651: left permissive on purpose; the reason
#                and the caller are commented at the class)

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.client_log import ClientLogLevel


class ClientLogCreate(BaseModel):
    """Single client log record. Validation is intentionally light - the
    service drops malformed records individually rather than rejecting
    the whole batch, so a buggy frontend can't silently lose every
    log line until someone fixes the schema.

    DWB-651: DELIBERATELY PERMISSIVE - no extra="forbid" here, and this is the
    one write path in the API that cannot have it. CALLER:
    `frontend/src/services/logger`, batching browser telemetry (nav, fetch
    lifecycle, render errors). This class is NOT a FastAPI request body: the
    route takes `list[dict]` and re-validates each item here, which is what
    keeps one bad record from 422ing the whole batch. Forbidding at this level
    would drop a whole record for one stray key and lose the surrounding trail.
    The full rationale, including the never-5xx contract, is on the route:
    see `app/routers/client_logs.py::post_client_logs`.
    """

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
