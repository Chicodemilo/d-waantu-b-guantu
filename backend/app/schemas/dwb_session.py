# Path: app/schemas/dwb_session.py
# File: dwb_session.py
# Created: 2026-06-09
# Purpose: Pydantic schemas for DWB session CRUD + lifecycle + rollup endpoints (DWB-335, DWB-336, DWB-338, DWB-346 list aggregates + headline, DWB-353 ad_hoc bucket, DWB-481 structured summary JSON, DWB-493 summary+keywords on list/detail read, DWBG-011 cross-session search result row)
# Caller: app/routers/dwb_sessions.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: DwbSessionCreate, DwbSessionUpdate, DwbSessionRead, DwbSessionOpenRequest, DwbSessionCloseRequest, DwbSessionOpenConflict, DwbSessionKeyword, DwbSessionListItem, DwbSessionByRoleEntry, DwbSessionByTicketEntry, DwbSessionDetail, DwbSessionSearchResult, DwbSessionRecentItem, DwbSessionNarrativeResult
# Last Modified: 2026-06-25 (DWB-493 summary+keywords on read; DWB-500 keyword weight is a TF-IDF relevance score; DWBG-014 generate-narrative result; DWBG-016 recent sessions row)

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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
    # DWB-481: structured bulleted write-up (free-form JSON, synthesizer-owned).
    summary: dict | list | None = None


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
    # DWB-481: structured bulleted write-up (free-form JSON). None until synthesized.
    summary: dict | list | None = None
    is_open: int | None
    created_at: datetime
    updated_at: datetime


class DwbSessionOpenRequest(BaseModel):
    """POST /api/sessions/open body (DWB-336).

    Same shape as DwbSessionCreate but kept distinct so the endpoint signature
    can evolve without disturbing model-level CRUD usage.

    opened_at is OPTIONAL. Deterministic callers (the regex/transcript/slash
    hooks) may pass a real machine-clock anchor. The AI/manual TL layer
    (ai_confident / ai_asked) MUST omit it: the service ignores any value on
    those methods and stamps the server clock, because a language-model-built
    timestamp can be hours wrong. When omitted on any method, the server
    defaults opened_at to datetime.now(UTC)."""

    project_id: int
    opened_at: datetime | None = None
    open_method: DwbOpenMethod
    open_phrase: str | None = None


class DwbSessionCloseRequest(BaseModel):
    """POST /api/sessions/{id}/close body (DWB-336, DWB-346).

    close_method + close_reason are required so the rollup row records which
    layer (regex / ai_confident / ai_asked / idle_timeout) caught the close
    and why (explicit / idle / manual). close_phrase is optional - the idle
    sweeper (DWB-337) has no phrase to attribute. closed_at is optional;
    omitted means 'now' (server-side default).

    headline (DWB-346): short summary (5-10 words, <=80 chars) of what the
    session was about. Persisted on dwb_sessions.headline; surfaced by the
    list endpoint as the per-session SUMMARY (it differentiates sessions that
    share an epic, which the auto-derived ticket_summary cannot).

    REQUIRED for human/AI/slash closes: the endpoint rejects a missing/blank
    headline with a 422 that instructs the closing agent how to write one.
    Only the idle sweeper (close_method=idle_timeout) is exempt — it has no
    summariser. Kept nullable here (rather than a required str) so the request
    still parses and reaches the endpoint, which returns the helpful,
    window-aware message instead of a generic Pydantic validation error.
    """

    close_method: DwbCloseMethod
    close_reason: DwbCloseReason
    close_phrase: str | None = None
    closed_at: datetime | None = None
    headline: str | None = None
    # DWBG-007: optional TL-authored narrative — the interpretive layer
    # (decisions, blockers, next-steps) the deterministic summary cannot
    # produce. Free-form JSON, same shape as `summary` so the frontend renders
    # both uniformly. Only persisted on conscious closes (ai_confident /
    # ai_asked); additive and best-effort, so omitting it never blocks a close.
    # Authored over agent/tool turns only (never user prompts; DWBG-003).
    narrative: dict | list | None = None


class DwbSessionOpenConflict(BaseModel):
    """409 response body for POST /api/sessions/open and
    POST /api/sessions/{id}/reopen (DWB-395) when a session is already open for
    the project. Surfaces the active session's id + opened_at so the caller can
    debug ('why didn't my open/reopen succeed?') without a follow-up GET.

    ``headline`` (DWB-395) carries the active session's user-facing summary when
    one is set, so the conflict names the blocking session rather than forcing
    the caller to look it up. None when the active session has no headline."""

    detail: str
    active_session_id: int
    opened_at: datetime
    headline: str | None = None


# ---------------------------------------------------------------------------
# Rollup endpoint schemas (DWB-338)
# ---------------------------------------------------------------------------


class DwbSessionKeyword(BaseModel):
    """One weighted keyword for a session (DWB-493), mined by the close-time
    synthesizer (DWB-484) and stored in entity_keywords. The list endpoints
    surface these sorted by weight descending so the FE renders a tag row
    without its own sort. `weight` is an int TF-IDF RELEVANCE SCORE (DWB-500),
    not a raw occurrence count: terms common across many sessions are
    down-weighted so session-distinctive terms rank higher."""

    model_config = ConfigDict(from_attributes=True)

    keyword: str
    weight: int


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
    # DWB-493: structured write-up + weighted keywords surfaced on the list so
    # the dashboard can fuzzy-match / preview without a per-row detail fetch.
    summary: dict | list | None = None
    keywords: list[DwbSessionKeyword] = Field(default_factory=list)


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
    # DWB-481: structured bulleted write-up mirrored from the row (None until synthesized).
    summary: dict | list | None = None
    # DWBG-007: TL-authored interpretive narrative + provenance (None until authored).
    narrative: dict | list | None = None
    narrative_author: str | None = None
    narrative_generated_at: datetime | None = None
    # DWB-493: weighted keywords for this session, sorted weight desc.
    keywords: list[DwbSessionKeyword] = Field(default_factory=list)
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


# ---------------------------------------------------------------------------
# Cross-session search (DWBG-011)
# ---------------------------------------------------------------------------


class DwbSessionSearchResult(BaseModel):
    """One ranked row from GET /api/sessions/search (DWBG-011).

    Deliberately slim - the search results page renders cards and links each to
    the detail endpoint, so it does not need the full rollup. Carries enough to
    render a result card: the session identity, when it ran, its token cost, a
    matched snippet of prose, and the weighted keyword chips (reused from the
    DWB-493 batched keyword read).

    `relevance` is the raw MySQL FULLTEXT MATCH score (natural-language mode).
    `keyword_boost` is the summed entity_keywords.weight for keywords whose term
    matched the query; `score` is the combined rank value the rows were sorted
    by (relevance + a fixed multiple of keyword_boost), exposed so the frontend
    can show why a row ranked where it did and so tests can assert ordering.
    `snippet` is a short slice of search_text around the first matched term,
    or the headline when no inline match window is found.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    headline: str | None = None
    opened_at: datetime
    closed_at: datetime | None
    total_tokens: int
    relevance: float
    keyword_boost: float
    score: float
    snippet: str | None = None
    keywords: list[DwbSessionKeyword] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Cross-project recent sessions (DWBG-016 dependency, for the Recall page)
# ---------------------------------------------------------------------------


class DwbSessionRecentItem(BaseModel):
    """One row from GET /api/sessions/recent (DWBG-016 dependency).

    Cross-project, newest-first, slim — the same fields as a search result row so
    Freddie's Recall page can render recent sessions by default with the same card
    component it uses for search hits, just without the relevance/score fields.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    headline: str | None = None
    opened_at: datetime
    closed_at: datetime | None
    total_tokens: int
    keywords: list[DwbSessionKeyword] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# On-demand narrative generation (DWBG-014)
# ---------------------------------------------------------------------------


class DwbSessionNarrativeResult(BaseModel):
    """Response body for POST /api/sessions/{id}/generate-narrative (DWBG-014).

    `generated` is True when the summarizer produced and persisted a narrative,
    False when it was skipped (no API key, no agent evidence in the window, an API
    error, or an unparseable response) — generation is best-effort, so a skip is a
    200 with generated=False, not an error. `narrative` carries the persisted JSON
    when generated, else the session's existing narrative (which may be None or a
    prior TL/summarizer narrative)."""

    session_id: int
    generated: bool
    narrative_author: str | None = None
    narrative_generated_at: datetime | None = None
    narrative: dict | list | None = None
