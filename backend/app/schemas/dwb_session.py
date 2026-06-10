# Path: app/schemas/dwb_session.py
# File: dwb_session.py
# Created: 2026-06-09
# Purpose: Pydantic schemas for DWB session CRUD + lifecycle + rollup endpoints (DWB-335, DWB-336, DWB-338, DWB-346 list aggregates + headline, DWB-353 ad_hoc bucket)
# Caller: app/routers/dwb_sessions.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: DwbSessionCreate, DwbSessionUpdate, DwbSessionRead, DwbSessionOpenRequest, DwbSessionCloseRequest, DwbSessionOpenConflict, DwbSessionListItem, DwbSessionByRoleEntry, DwbSessionByTicketEntry, DwbSessionDetail
# Last Modified: 2026-06-10

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
    # DWB-346: user-supplied summary set on close. None when never set.
    headline: str | None = None
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
    """POST /api/sessions/{id}/close body (DWB-336, DWB-346).

    close_method + close_reason are required so the rollup row records which
    layer (regex / ai_confident / ai_asked / idle_timeout) caught the close
    and why (explicit / idle / manual). close_phrase is optional - the idle
    sweeper (DWB-337) has no phrase to attribute. closed_at is optional;
    omitted means 'now' (server-side default).

    headline (DWB-346): optional short summary (<=80 chars) of what the
    session was about. Persisted on dwb_sessions.headline; surfaced by the
    list endpoint. None means 'use the auto-derived ticket_summary instead'.
    """

    close_method: DwbCloseMethod
    close_reason: DwbCloseReason
    close_phrase: str | None = None
    closed_at: datetime | None = None
    headline: str | None = None


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
    closed_at IS NULL, else "closed".

    DWB-346 added per-row aggregates so the dashboard can render a useful
    sessions list without a fan-out N+1 to the detail endpoint:

      - tickets_made:      tickets whose created_at falls in the session window
      - tickets_completed: tickets whose completed_at falls in the session window
      - agents_active:     distinct agent count from linked hook_sessions
      - open_method:       same enum that lives on the row
      - close_method:      same enum (None for still-open sessions)
      - headline:          the user-supplied summary set on close (DWB-346)
      - ticket_summary:    auto-derived "Epic Name (N)" string built from
                            the completed tickets in the window; None when no
                            ticket completed in this session
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    opened_at: datetime
    closed_at: datetime | None
    total_tokens: int
    total_time_seconds: int
    status: str
    # DWB-346 fields below. All optional/defaulted so older callers that
    # only consume the first six keys are unaffected.
    headline: str | None = None
    tickets_made: int = 0
    tickets_completed: int = 0
    agents_active: int = 0
    open_method: DwbOpenMethod | None = None
    close_method: DwbCloseMethod | None = None
    ticket_summary: str | None = None
    # DWB-353: ad_hoc overhead bucket (worker tokens without ticket).
    ad_hoc_overhead_tokens: int = 0
    ad_hoc_overhead_seconds: int = 0


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
    # DWB-346: user-supplied headline mirrored from the row.
    headline: str | None = None
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
    # DWB-353: ad_hoc bucket (worker tokens without ticket attribution in window).
    ad_hoc_overhead_tokens: int = 0
    ad_hoc_overhead_seconds: int = 0
