# Path: app/services/dwb_session.py
# File: dwb_session.py
# Created: 2026-06-09
# Purpose: Service-layer business logic for DWB session open/close + idle sweep (DWB-336, DWB-337, DWB-346 headline, DWB-351 privacy null-out on AI-layer phrases, DWB-382 ai_classifier added to AI-set)
# Caller: app/services/idle_sweeper.py (sweep loop), app/routers/dwb_sessions.py (open + close endpoints)
# Callees: app.models.dwb_session, app.models.hook_session, app.models.tracking_log, app.database.SessionLocal
# Data In: SQLAlchemy Session + DwbSession instance (close) or project_id/opened_at (open)
# Data Out: Open/closed DwbSession rows, idle-sweep counts
# Last Modified: 2026-06-11

"""DWB session business logic.

Three responsibilities live here:

1. **open_session** — single source of truth for opening a DwbSession.
   Pre-checks the single-active invariant (at most one open DwbSession per
   project) and returns either the new row or the existing active row so
   the caller can translate to HTTP 201/409 (DWB-336).

2. **close_session** — single source of truth for closing a DwbSession.
   Sets closed_at, close_method, close_reason, close_phrase, total_tokens
   (rolled up from linked hook_sessions), and total_time_seconds (wall
   clock from opened_at). Used by:
     - the idle sweeper for `close_method=idle_timeout`
     - DWB-336's POST /api/sessions/{id}/close endpoint for explicit close

3. **sweep_idle_sessions** — one pass of the idle-timeout sweeper. Finds
   every open session whose last activity is older than IDLE_TIMEOUT_MINUTES
   and closes it with `close_method=idle_timeout`, `close_reason=idle`,
   `close_phrase=None`.

Activity for "last_activity" comes from two sources:
  - hook_sessions: linked via dwb_session_id, OR matching the session's
    project_id with end_time >= opened_at (handles hook_sessions that
    ingested before the link was wired)
  - tracking_log: matching the session's project_id with timestamp >=
    opened_at (tracking_log has no dwb_session_id; see DWB-335 scope)

If no activity is found, last_activity = opened_at — so a freshly-opened
session with no work yet won't be auto-closed before the idle window has
elapsed since open.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession
from app.models.tracking_log import TrackingLog


def _utcnow() -> datetime:
    """Naive UTC, matching MySQL DATETIME columns."""
    return datetime.utcnow()


def _strip_tz(dt: datetime) -> datetime:
    """Normalise a datetime to naive UTC for MySQL DATETIME columns.

    Callers (REST endpoints, hook handlers) routinely pass aware datetimes
    parsed from ISO 8601 strings. The DwbSession columns are naive; mixing
    aware/naive triggers ``TypeError: can't subtract offset-naive and
    offset-aware datetimes`` in the rollup arithmetic.
    """
    if dt.tzinfo is not None:
        from datetime import timezone

        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def get_active_session(db: Session, project_id: int) -> DwbSession | None:
    """Return the one open DwbSession for a project, or None.

    The (project_id, is_open) UNIQUE index (DWB-335) guarantees at most one
    row with closed_at IS NULL per project, so this returns at most one
    row by design. Convenience lookup used by the open endpoint to populate
    the 409 conflict body, and by tests that need to assert single-active.
    """
    return db.execute(
        select(DwbSession)
        .where(DwbSession.project_id == project_id)
        .where(DwbSession.closed_at.is_(None))
    ).scalar_one_or_none()


def open_session(
    db: Session,
    *,
    project_id: int,
    opened_at: datetime,
    open_method: DwbOpenMethod,
    open_phrase: str | None = None,
) -> tuple[DwbSession | None, DwbSession | None]:
    """Open a new DWB session for a project.

    Returns a ``(new_session, existing_active)`` tuple:

      - On success:  ``(DwbSession, None)`` — new row created, flushed
                      so id + is_open are populated.
      - On conflict: ``(None, DwbSession)`` — an open session already
                      exists for the project. Caller (router) translates
                      this to HTTP 409 with the active session's id +
                      opened_at in the body for debuggability.

    The caller owns the commit; this function flushes only.

    The DB also enforces single-active via the (project_id, is_open) UNIQUE
    index, so racing opens still fail safely with IntegrityError — this
    pre-check is for the friendly conflict body, not correctness.

    DWB-351 privacy guard: when ``open_method`` is ``ai_confident``,
    ``ai_asked``, or ``ai_classifier`` (DWB-382), the user's literal
    text is never persisted - the ``open_phrase`` field is silently
    nulled out regardless of what the caller passed. Regex opens may
    continue to store the matched catalogue substring (deterministic,
    bounded by the hardcoded phrase list in
    ``app.config.session_phrases``); ``slash`` opens persist the static
    `/dwb-open` token. Silent rather than 400 by design (TL playbook
    recommends omitting the field for AI opens, but a stale caller that
    still sends it gets quiet
    null-out instead of a hard failure).
    """
    existing = get_active_session(db, project_id)
    if existing is not None:
        return None, existing

    # DWB-351: privacy null-out on AI-layer opens. DWB-382 added
    # ai_classifier to the AI set.
    if open_method in (
        DwbOpenMethod.ai_confident,
        DwbOpenMethod.ai_asked,
        DwbOpenMethod.ai_classifier,
    ):
        open_phrase = None

    row = DwbSession(
        project_id=project_id,
        opened_at=_strip_tz(opened_at),
        open_method=open_method,
        open_phrase=open_phrase,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return row, None


def compute_last_activity(db: Session, session: DwbSession) -> datetime:
    """Return the most recent activity timestamp for a DWB session.

    Considers, since the session's opened_at:
      - hook_sessions linked to this session (dwb_session_id = session.id)
      - hook_sessions for the same project (covers pre-link history)
      - tracking_log entries for the same project

    Returns `session.opened_at` if no activity is observed — the caller can
    then compare against (now - idle_threshold) to decide whether to close.
    """
    opened_at = session.opened_at

    hook_max = db.execute(
        select(func.max(HookSession.end_time)).where(
            HookSession.end_time.isnot(None),
            HookSession.end_time >= opened_at,
            or_(
                HookSession.dwb_session_id == session.id,
                HookSession.project_id == session.project_id,
            ),
        )
    ).scalar()

    # Also consider hook_sessions that are *still open* (end_time IS NULL)
    # but whose start_time is recent — an active worker that just started
    # should count as activity. Use start_time as a fallback signal.
    hook_start_max = db.execute(
        select(func.max(HookSession.start_time)).where(
            HookSession.end_time.is_(None),
            HookSession.start_time >= opened_at,
            or_(
                HookSession.dwb_session_id == session.id,
                HookSession.project_id == session.project_id,
            ),
        )
    ).scalar()

    tracking_max = db.execute(
        select(func.max(TrackingLog.timestamp)).where(
            TrackingLog.project_id == session.project_id,
            TrackingLog.timestamp >= opened_at,
        )
    ).scalar()

    candidates = [
        c for c in (opened_at, hook_max, hook_start_max, tracking_max) if c is not None
    ]
    return max(candidates)


def _rollup_tokens(db: Session, session: DwbSession) -> int:
    """Sum hook_sessions.total_tokens linked to this DWB session.

    Only counts hook_sessions where dwb_session_id = session.id — we do NOT
    fall back to project-wide hook_sessions for the token total, because
    that would double-count work from prior DWB sessions on the same
    project. Pre-link history (FK NULL) contributes nothing to the rollup
    by design (DWB-335 scope: no backfill).
    """
    total = db.execute(
        select(func.coalesce(func.sum(HookSession.total_tokens), 0)).where(
            HookSession.dwb_session_id == session.id,
        )
    ).scalar()
    return int(total or 0)


def close_session(
    db: Session,
    session: DwbSession,
    *,
    close_method: DwbCloseMethod,
    close_reason: DwbCloseReason,
    close_phrase: str | None = None,
    now: datetime | None = None,
    headline: str | None = None,
) -> DwbSession:
    """Close an open DwbSession. Idempotent: if the session is already closed,
    returns it unchanged (no double-close, no overwrite of close fields).

    Callers (idle sweeper, DWB-338 close endpoint) own the commit.

    Computes:
      - closed_at = now (default utcnow)
      - total_tokens = sum of linked hook_sessions.total_tokens
      - total_time_seconds = (closed_at - opened_at).total_seconds()
      - headline (DWB-346) = passthrough; persisted when non-None. The idle
        sweeper never supplies one (machine-driven close has nothing to
        say); only the explicit close endpoint does.

    DWB-351 privacy guard: when ``close_method`` is ``ai_confident``,
    ``ai_asked``, or ``ai_classifier`` (DWB-382) the ``close_phrase`` is
    silently nulled out before persisting. Regex / slash closes may store
    the matched catalogue substring or the static `/dwb-close` token;
    idle_timeout closes never receive a phrase to begin with. See
    ``open_session`` for the matching open-side guard.
    """
    if session.closed_at is not None:
        return session

    # DWB-351: privacy null-out on AI-layer closes. DWB-382 added
    # ai_classifier to the AI set.
    if close_method in (
        DwbCloseMethod.ai_confident,
        DwbCloseMethod.ai_asked,
        DwbCloseMethod.ai_classifier,
    ):
        close_phrase = None

    closed_at = _strip_tz(now) if now is not None else _utcnow()
    session.closed_at = closed_at
    session.close_method = close_method
    session.close_reason = close_reason
    session.close_phrase = close_phrase
    if headline is not None:
        session.headline = headline
    session.total_tokens = _rollup_tokens(db, session)
    session.total_time_seconds = max(
        0, int((closed_at - session.opened_at).total_seconds())
    )
    db.flush()
    return session


def find_idle_sessions(
    db: Session, *, idle_minutes: int, now: datetime | None = None
) -> list[DwbSession]:
    """Return every open DwbSession whose last activity is older than the
    idle threshold. Sessions with `closed_at IS NOT NULL` are skipped."""
    now = now or _utcnow()
    cutoff = now - timedelta(minutes=idle_minutes)

    open_sessions: Iterable[DwbSession] = db.execute(
        select(DwbSession).where(DwbSession.closed_at.is_(None))
    ).scalars()

    idle: list[DwbSession] = []
    for s in open_sessions:
        if compute_last_activity(db, s) <= cutoff:
            idle.append(s)
    return idle


def sweep_idle_sessions(
    db: Session,
    *,
    idle_minutes: int,
    now: datetime | None = None,
) -> int:
    """Close every open DwbSession whose last activity is older than the idle
    threshold. Returns the count closed. The caller owns the commit."""
    closed_count = 0
    for s in find_idle_sessions(db, idle_minutes=idle_minutes, now=now):
        close_session(
            db,
            s,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
            close_phrase=None,
            now=now,
        )
        closed_count += 1
    return closed_count
