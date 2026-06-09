# Path: app/schemas/dwb_session.py
# File: dwb_session.py
# Created: 2026-06-09
# Purpose: Pydantic schemas for DWB session CRUD + lifecycle + rollup endpoints (DWB-335, DWB-336, DWB-338)
# Caller: app/routers/dwb_sessions.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: DwbSessionCreate, DwbSessionUpdate, DwbSessionRead, DwbSessionOpenRequest, DwbSessionCloseRequest, DwbSessionOpenConflict, DwbSessionListItem, DwbSessionByRoleEntry, DwbSessionByTicketEntry, DwbSessionDetail
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


class DwbSessionOpenRequest(BaseModel):
    """POST /api/sessions/open body (DWB-336).

    Same shape as DwbSessionCreate but kept distinct so the endpoint signature
    can evolve without disturbing model-level CRUD usage. opened_at is required
    so the caller controls when the session is anchored (regex hook uses the
    SessionStart timestamp; TL AI uses the user-turn timestamp)."""

    project_id: int
    opened_at: datetime
    open_method: DwbOpenMethod
    open_phrase: str | None = None


class DwbSessionCloseRequest(BaseModel):
    """POST /api/sessions/{id}/close body (DWB-336).

    close_method + close_reason are required so the rollup row records which
    layer (regex / ai_confident / ai_asked / idle_timeout) caught the close
    and why (explicit / idle / manual). close_phrase is optional — the idle
    sweeper (DWB-337) has no phrase to attribute. closed_at is optional;
    omitted means 'now' (server-side default)."""

    close_method: DwbCloseMethod
    close_reason: DwbCloseReason
    close_phrase: str | None = None
    closed_at: datetime | None = None


class DwbSessionOpenConflict(BaseModel):
    """409 response body for POST /api/sessions/open when a session is already
    open for the project. Surfaces the active session's id + opened_at so
    the caller can debug ('why didn't my open succeed?') without a follow-up
    GET."""

    detail: str
    active_session_id: int
    opened_at: datetime


# ---------------------------------------------------------------------------
# Rollup endpoint schemas (DWB-338)
# ---------------------------------------------------------------------------


class DwbSessionListItem(BaseModel):
    """One row in GET /api/projects/{id}/sessions. Status is "open" when
    closed_at IS NULL, else "closed"."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    opened_at: datetime
    closed_at: datetime | None
    total_tokens: int
    total_time_seconds: int
    status: str


class DwbSessionByRoleEntry(BaseModel):
    """One row in DwbSessionDetail.by_role — tokens + clamped wall-clock time
    attributed to a single agent within the session window."""

    agent_id: int
    agent_name: str
    role: str
    tokens: int
    time_seconds: int


class DwbSessionByTicketEntry(BaseModel):
    """One row in DwbSessionDetail.by_ticket — tokens (token_report sum) +
    time (start/stop pairing clamped to window) for a single ticket."""

    ticket_id: int
    ticket_key: str
    title: str
    tokens: int
    time_seconds: int


class DwbSessionDetail(BaseModel):
    """GET /api/sessions/{id} response body. For open sessions, totals are
    live partials — `live` is True, status is "open", and tokens that pend
    on a still-active Claude Code session (notably the TL's own) are NOT
    yet reflected. For closed sessions the totals match the stored
    dwb_sessions.total_tokens / total_time_seconds (frozen at close)."""

    # meta
    id: int
    project_id: int
    opened_at: datetime
    closed_at: datetime | None
    open_phrase: str | None
    close_phrase: str | None
    open_method: DwbOpenMethod
    close_method: DwbCloseMethod | None
    close_reason: DwbCloseReason | None
    # status / live partials flag
    status: str
    live: bool
    # totals
    total_tokens: int
    total_time_seconds: int
    # slices
    by_role: list[DwbSessionByRoleEntry]
    by_ticket: list[DwbSessionByTicketEntry]
    # overhead deltas during window
    tl_overhead_tokens: int
    pm_overhead_tokens: int
