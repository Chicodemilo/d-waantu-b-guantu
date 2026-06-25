# Path: app/services/dwb_session.py
# File: dwb_session.py
# Created: 2026-06-09
# Purpose: Service-layer business logic for DWB session open/close/reopen + idle sweep (DWB-336, DWB-337, DWB-346 headline, DWB-351 privacy null-out on AI-layer phrases, DWB-382 ai_classifier added to AI-set, DWB-395 reopen_session, DWB-484 close-time write-up synthesis: headline/summary/keywords)
# Caller: app/services/idle_sweeper.py (sweep loop), app/routers/dwb_sessions.py (open + close + reopen endpoints), app/services/hook_tracking.py (grace-window resurrect)
# Callees: app.models.dwb_session, app.models.hook_session, app.models.tracking_log, app.models.entity_keyword, app.models.ticket, app.models.comment, app.models.inter_agent_message, app.services.dwb_session_rollup, app.services.keyword_extraction, app.services.session_synthesizer, app.database.SessionLocal
# Data In: SQLAlchemy Session + DwbSession instance (close) or project_id/opened_at (open)
# Data Out: Open/closed DwbSession rows, idle-sweep counts
# Last Modified: 2026-06-25 (DWB-484: synthesize + persist headline/summary/keywords on every close path)

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

import logging
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.comment import Comment
from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.entity_keyword import EntityKeyword
from app.models.hook_session import HookSession
from app.models.inter_agent_message import InterAgentMessage
from app.models.ticket import Ticket
from app.models.tracking_log import TrackingLog
from app.services import dwb_session_rollup as rollup_svc
from app.services.activity_log import log_activity
from app.services.keyword_extraction import extract_keywords
from app.services.session_synthesizer import synthesize_session_summary

logger = logging.getLogger(__name__)

# DWB-484: keywords mined at session close are tagged with this source label
# on their EntityKeyword rows (entity_type='dwb_session').
_KEYWORD_SOURCE = "session_synth"


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
    opened_at: datetime | None = None,
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

    Timestamp authority: ``opened_at`` is optional. For the ``ai_confident``
    and ``ai_asked`` methods (the language-model TL layer) any caller-supplied
    value is ignored and the server stamps ``datetime.now(UTC)`` — the LLM
    must not anchor the session, because a fabricated timestamp can be hours
    off. For every other method an explicit ``opened_at`` is honoured (the
    hooks pass a real machine clock); when omitted, it defaults to now().

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

    # Timestamp authority. The ai_confident/ai_asked methods are the only
    # callers where a language model (the TL main loop) hand-builds opened_at,
    # and a fabricated value can be off by hours (observed: a model passed
    # midnight-UTC, which rendered as 7pm-prior-day in local time). Those two
    # methods therefore do NOT control the anchor: the server always stamps
    # now(). This mirrors the privacy null-out below — the LLM cannot set the
    # value, so it cannot get it wrong. All other methods (regex/transcript/
    # slash/idle/ai_classifier) carry a real machine clock and keep their
    # explicit anchor; if omitted, the server defaults to now().
    if open_method in (DwbOpenMethod.ai_confident, DwbOpenMethod.ai_asked):
        opened_at = datetime.now(UTC)
    elif opened_at is None:
        opened_at = datetime.now(UTC)

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

    # DWB-411: semantic session_opened event. flush-only, like the row above —
    # the caller owns the commit. agent_id is None: a DWB session is a
    # project-level construct opened by the TL/hooks, not an individual agent.
    # entity_type='session' matches the middleware's URL-derived type for
    # /api/sessions so the read-side feed dedup (DWB-409) collapses the generic
    # sibling row.
    log_activity(
        db, project_id, None, "session", row.id, "session_opened",
        {"open_method": open_method.value},
    )
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


# ---------------------------------------------------------------------------
# DWB-484: session write-up synthesis (headline + summary + keywords) on close
# ---------------------------------------------------------------------------


def _gather_corpus(
    db: Session,
    session: DwbSession,
    win_start: datetime,
    win_end: datetime,
    by_role: list[dict],
    by_ticket: list[dict],
) -> list[str]:
    """Assemble the keyword-extraction corpus for a session window (DWB-482/484).

    AGENT-PRODUCED TEXT ONLY (HARD PRIVACY RULE, DWB-351): ticket keys + titles +
    descriptions, inter-agent comms (body + summary), ticket comments, and
    agent/role names. NEVER user-typed prompt text - DWB persists none, and this
    gathering layer must not introduce any.
    """
    texts: list[str] = []

    # Tickets created OR completed in the window, plus any worked (by_ticket).
    ticket_ids = {t["ticket_id"] for t in by_ticket if t.get("ticket_id")}
    window_tickets = db.execute(
        select(Ticket)
        .where(Ticket.project_id == session.project_id)
        .where(
            or_(
                (Ticket.created_at >= win_start) & (Ticket.created_at <= win_end),
                (Ticket.completed_at.isnot(None))
                & (Ticket.completed_at >= win_start)
                & (Ticket.completed_at <= win_end),
            )
        )
    ).scalars().all()
    seen_ids: set[int] = set()
    for t in window_tickets:
        seen_ids.add(t.id)
        # ticket_key (DWB-900) is kept verbatim by the extractor regardless of
        # frequency, so a session always yields at least its tickets as keywords.
        if t.ticket_key:
            texts.append(t.ticket_key)
        if t.title:
            texts.append(t.title)
        if t.description:
            texts.append(t.description)
    # Worked tickets not already pulled above (touched but neither created nor
    # completed in the window).
    missing = ticket_ids - seen_ids
    if missing:
        for t in db.execute(
            select(Ticket).where(Ticket.id.in_(missing))
        ).scalars().all():
            if t.ticket_key:
                texts.append(t.ticket_key)
            if t.title:
                texts.append(t.title)
            if t.description:
                texts.append(t.description)

    # Agent + role names (system/agent vocabulary, not user text).
    for r in by_role:
        if r.get("agent_name"):
            texts.append(r["agent_name"])
        if r.get("role"):
            texts.append(r["role"])

    # Inter-agent comms linked to this DWB session (body + summary).
    for m in db.execute(
        select(InterAgentMessage).where(
            InterAgentMessage.dwb_session_id == session.id
        )
    ).scalars().all():
        if m.body:
            texts.append(m.body)
        if m.summary:
            texts.append(m.summary)

    # Ticket comments authored in the window on tickets touched this session.
    all_ticket_ids = seen_ids | ticket_ids
    if all_ticket_ids:
        for c in db.execute(
            select(Comment)
            .where(Comment.ticket_id.in_(all_ticket_ids))
            .where(Comment.created_at >= win_start)
            .where(Comment.created_at <= win_end)
        ).scalars().all():
            if c.body:
                texts.append(c.body)

    return texts


def _assemble_rollup(
    db: Session,
    session: DwbSession,
    *,
    now: datetime,
    supplied_headline: str | None,
) -> dict:
    """Build the synthesizer's rollup dict (DWB-484) from the read-only rollup
    helpers + a privacy-safe corpus + the DWB-482 pure keyword extractor. Pure
    data assembly; the synthesizer itself (DWB-483) does the distillation.

    Corpus gathering (``_gather_corpus``) is agent-produced text only (DWB-351):
    ticket keys/titles/descriptions, session-linked comms, in-window comments,
    agent/role names - never user prompt text."""
    win_start, win_end = rollup_svc.compute_window(session, now=now)
    by_role = rollup_svc.compute_by_role(db, session, now=now)
    by_ticket = rollup_svc.compute_by_ticket(db, session, now=now)
    aggs = rollup_svc.compute_list_aggregates(db, session, now=now)

    # Completed-in-window tickets with key+title for named summary bullets.
    completed_tickets = [
        {"ticket_key": key, "title": title}
        for key, title in db.execute(
            select(Ticket.ticket_key, Ticket.title)
            .where(Ticket.project_id == session.project_id)
            .where(Ticket.completed_at.isnot(None))
            .where(Ticket.completed_at >= win_start)
            .where(Ticket.completed_at <= win_end)
            .order_by(Ticket.completed_at.asc())
        ).all()
    ]

    corpus = _gather_corpus(db, session, win_start, win_end, by_role, by_ticket)
    keywords = [(kw.keyword, kw.weight) for kw in extract_keywords(corpus)]

    return {
        "headline": supplied_headline,
        "by_role": by_role,
        "by_ticket": by_ticket,
        "tickets_made": aggs.get("tickets_made", 0),
        "tickets_completed": aggs.get("tickets_completed", 0),
        "agents_active": aggs.get("agents_active", 0),
        "ticket_summary": aggs.get("ticket_summary"),
        "completed_tickets": completed_tickets,
        "total_tokens": int(session.total_tokens or 0),
        "total_time_seconds": int(session.total_time_seconds or 0),
        "keywords": keywords,
    }


def _apply_synthesis(
    db: Session, session: DwbSession, *, now: datetime
) -> None:
    """DWB-484: synthesize headline/summary/keywords and persist them onto the
    closing session. Keeps a supplied headline, synthesizes when null (the
    null-headline fix). Idempotent on reopen/re-close: existing session keyword
    rows are cleared before reinsert. flush-only; the caller owns the commit.

    Guarded: a synthesis failure must NEVER block a close. The read/compute
    phase is isolated in a try that returns early on error WITHOUT writing
    anything, so the close stamps (already set by the caller) are never rolled
    back. We deliberately do NOT call db.rollback() here - that would discard
    the in-flight close on the shared transaction."""
    # Read/compute phase - pure reads + the pure synthesizer. If anything here
    # throws, nothing has been written yet, so the close proceeds untouched.
    try:
        rollup = _assemble_rollup(
            db, session, now=now, supplied_headline=session.headline
        )
        result = synthesize_session_summary(rollup)
    except Exception:
        logger.warning(
            "session synthesis failed for DWB session %s; closing without it",
            session.id, exc_info=True,
        )
        return

    # Write phase - trivial ORM ops on the same uncommitted transaction.
    # Keep a supplied headline; synthesize only when none was set.
    if session.headline is None:
        session.headline = result["headline"]
    session.summary = result["summary"]

    # Idempotent: drop any prior keyword rows for this session before
    # reinserting (covers reopen -> re-close recompute).
    db.execute(
        EntityKeyword.__table__.delete().where(
            (EntityKeyword.entity_type == "dwb_session")
            & (EntityKeyword.entity_id == session.id)
        )
    )
    for kw in result["keywords"]:
        db.add(EntityKeyword(
            entity_type="dwb_session",
            entity_id=session.id,
            keyword=kw["keyword"],
            weight=kw["weight"],
            source=_KEYWORD_SOURCE,
        ))
    db.flush()


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
      - headline (DWB-346) = passthrough; persisted when non-None. When the
        caller supplies none (regex/slash/idle closes), DWB-484 synthesizes one
        from the rollup so the session is never left blank.
      - summary (DWB-484) = structured write-up JSON, synthesized from the
        rollup; weighted keyword rows (EntityKeyword) are inserted alongside.

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

    # DWB-484: synthesize the write-up over the session rollup and persist it -
    # headline (only when the caller supplied none -> fixes the null-headline
    # bug on regex/slash/idle closes), structured `summary` JSON, and weighted
    # EntityKeyword rows. Runs on EVERY close path because close_session is the
    # single funnel (the close endpoint and sweep_idle_sessions both route here).
    # Guarded internally so a synthesis failure never blocks the close, and
    # placed before the feed event so session_closed carries the final headline.
    _apply_synthesis(db, session, now=closed_at)

    # DWB-411: semantic session_closed event. Emitted only on a real close
    # (the already-closed early-return above skips it, so no double-emit on an
    # idempotent re-close). flush-only; the caller owns the commit.
    # entity_type='session' (see open_session) so feed dedup collapses the
    # generic middleware row.
    log_activity(
        db, session.project_id, None, "session", session.id, "session_closed",
        {
            "close_method": close_method.value,
            "headline": session.headline,
            "total_tokens": session.total_tokens,
        },
    )
    return session


def reopen_session(
    db: Session, session: DwbSession
) -> tuple[DwbSession | None, DwbSession | None]:
    """Reopen a closed DwbSession (DWB-395).

    Nulls ``closed_at`` / ``close_method`` / ``close_reason`` / ``close_phrase``
    so the row becomes active again. ``is_open`` is a generated STORED column
    that recomputes from ``closed_at`` (1 when NULL), so nulling ``closed_at``
    is sufficient to flip the single-active marker; the row is refreshed so the
    new ``is_open`` value is visible to the caller.

    Returns a ``(reopened, conflict)`` tuple mirroring ``open_session``:

      - ``(session, None)``   — success, or an idempotent no-op when the row
                                 was already open.
      - ``(None, existing)``  — another session is already open for this
                                 project; caller translates to HTTP 409. We do
                                 NOT touch the row in this case, so the
                                 (project_id, is_open) UNIQUE index is never
                                 tripped.

    The caller owns the commit; this function flushes only. The DB UNIQUE
    index is the backstop if a racing open lands between the pre-check and the
    flush.

    Totals (``total_tokens`` / ``total_time_seconds``) and ``headline`` are
    intentionally left as-is: they were frozen at the prior close and will be
    recomputed on the next close. The reopen only undoes the close stamp.
    """
    # Already open: nothing to undo. Idempotent success.
    if session.closed_at is None:
        return session, None

    # Single-active invariant: a different open session for this project blocks
    # the reopen. (The just-closed row we're reopening is, by definition, not
    # the active one, so get_active_session can only return a *different* row.)
    existing = get_active_session(db, session.project_id)
    if existing is not None and existing.id != session.id:
        return None, existing

    session.closed_at = None
    session.close_method = None
    session.close_reason = None
    session.close_phrase = None
    db.flush()
    db.refresh(session)
    return session, None


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
