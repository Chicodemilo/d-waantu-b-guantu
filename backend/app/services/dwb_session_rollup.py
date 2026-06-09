# Path: app/services/dwb_session_rollup.py
# File: dwb_session_rollup.py
# Created: 2026-06-09
# Purpose: Read-only rollups (by_role, by_ticket, overhead deltas) for DWB session detail endpoint (DWB-338)
# Caller: app/routers/dwb_sessions.py
# Callees: app.models.hook_session, app.models.tracking_log, app.models.agent, app.models.ticket
# Data In: SQLAlchemy Session + DwbSession instance
# Data Out: list[dict] for by_role / by_ticket, tuple[int,int] for overhead, tuple[int,int] for live totals
# Last Modified: 2026-06-09

"""DWB session rollup queries — read-only slices for the detail endpoint.

For a closed session, the slices reflect the frozen window
[opened_at, closed_at]. For an open session, the window ends at "now" and
the result is a live partial — workers' tokens that have already landed
via SubagentStop are present; the TL's own tokens only show up after
SessionEnd fires, so an open session usually under-reports the TL share.

All queries are project-scoped on `hook_sessions.project_id` /
`tracking_log.project_id` — cross-project agents that happen to be active
in the same wall-clock window are filtered out by construction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.dwb_session import DwbSession
from app.models.hook_session import HookSession
from app.models.ticket import Ticket
from app.models.tracking_log import TrackingLog


def _utcnow() -> datetime:
    return datetime.utcnow()


def compute_window(session: DwbSession, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the (start, end) window for rollup queries.

    For closed sessions the end is the recorded closed_at; for open sessions
    it is the current time (or the caller-supplied `now`, useful for tests).
    """
    end = session.closed_at if session.closed_at is not None else (now or _utcnow())
    return session.opened_at, end


def _clamp_duration(
    start: datetime, end: datetime, win_start: datetime, win_end: datetime
) -> int:
    """Intersect an interval [start, end] with the window and return the
    duration in whole seconds (0 if disjoint)."""
    lo = max(start, win_start)
    hi = min(end, win_end)
    if hi <= lo:
        return 0
    return int((hi - lo).total_seconds())


def compute_by_role(
    db: Session, session: DwbSession, *, now: datetime | None = None
) -> list[dict]:
    """Group hook_sessions by agent within the session window. Returns one
    entry per agent that ran any hook_session in the window, with role,
    name, total tokens, and clamped wall-clock time."""
    win_start, win_end = compute_window(session, now=now)

    rows: Iterable[tuple[HookSession, Agent]] = db.execute(
        select(HookSession, Agent)
        .join(Agent, HookSession.agent_id == Agent.id)
        .where(HookSession.project_id == session.project_id)
        .where(HookSession.start_time <= win_end)
        # Either still running, or ended after the window opened.
        .where(
            (HookSession.end_time.is_(None))
            | (HookSession.end_time >= win_start)
        )
    ).all()

    by_agent: dict[int, dict] = {}
    for hs, agent in rows:
        bucket = by_agent.setdefault(
            agent.id,
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "role": agent.role,
                "tokens": 0,
                "time_seconds": 0,
            },
        )
        bucket["tokens"] += int(hs.total_tokens or 0)
        effective_end = hs.end_time if hs.end_time is not None else win_end
        bucket["time_seconds"] += _clamp_duration(
            hs.start_time, effective_end, win_start, win_end
        )

    # Stable ordering: tokens desc, then agent_name asc (deterministic for tests).
    return sorted(
        by_agent.values(), key=lambda r: (-r["tokens"], r["agent_name"])
    )


def compute_by_ticket(
    db: Session, session: DwbSession, *, now: datetime | None = None
) -> list[dict]:
    """Group tracking_log token + time events by ticket within the session
    window. Token rollup sums `token_report` events; time rollup pairs
    `start` / `stop` events per ticket and clamps each interval to the
    window. Tickets touched only by overhead events (no ticket_id) are
    excluded by construction (filtered on ticket_id NOT NULL)."""
    win_start, win_end = compute_window(session, now=now)

    # Tokens by ticket — single aggregate query.
    token_rows = db.execute(
        select(
            TrackingLog.ticket_id,
            func.coalesce(func.sum(TrackingLog.tokens), 0).label("tokens"),
        )
        .where(TrackingLog.project_id == session.project_id)
        .where(TrackingLog.ticket_id.isnot(None))
        .where(TrackingLog.event_type == "token_report")
        .where(TrackingLog.timestamp >= win_start)
        .where(TrackingLog.timestamp <= win_end)
        .group_by(TrackingLog.ticket_id)
    ).all()
    tokens_by_ticket = {row.ticket_id: int(row.tokens) for row in token_rows}

    # Time by ticket — fetch ordered start/stop events in window per ticket
    # then pair them in Python.
    candidate_ticket_ids = set(tokens_by_ticket.keys())

    # Also pick up tickets that had start/stop events in the window but no
    # token_report (a worker who ran but didn't post tokens yet).
    extra_rows = db.execute(
        select(TrackingLog.ticket_id)
        .where(TrackingLog.project_id == session.project_id)
        .where(TrackingLog.ticket_id.isnot(None))
        .where(TrackingLog.event_type.in_(["start", "stop"]))
        .where(TrackingLog.timestamp >= win_start)
        .where(TrackingLog.timestamp <= win_end)
        .group_by(TrackingLog.ticket_id)
    ).all()
    for row in extra_rows:
        candidate_ticket_ids.add(row.ticket_id)

    if not candidate_ticket_ids:
        return []

    # Ticket meta lookup.
    tickets: dict[int, Ticket] = {
        t.id: t
        for t in db.execute(
            select(Ticket).where(Ticket.id.in_(candidate_ticket_ids))
        ).scalars()
    }

    # Time: pair start/stop events per ticket within the window.
    time_by_ticket: dict[int, int] = {tid: 0 for tid in candidate_ticket_ids}
    for tid in candidate_ticket_ids:
        events = list(
            db.scalars(
                select(TrackingLog)
                .where(TrackingLog.ticket_id == tid)
                .where(TrackingLog.event_type.in_(["start", "stop"]))
                .where(TrackingLog.timestamp >= win_start)
                .where(TrackingLog.timestamp <= win_end)
                .order_by(TrackingLog.timestamp.asc())
            ).all()
        )
        open_start: datetime | None = None
        for e in events:
            if e.event_type == "start":
                open_start = e.timestamp
            elif e.event_type == "stop" and open_start is not None:
                time_by_ticket[tid] += _clamp_duration(
                    open_start, e.timestamp, win_start, win_end
                )
                open_start = None
        # A dangling start (no matching stop within window) counts up to
        # the window end so a still-running ticket isn't invisible.
        if open_start is not None:
            time_by_ticket[tid] += _clamp_duration(
                open_start, win_end, win_start, win_end
            )

    entries: list[dict] = []
    for tid in candidate_ticket_ids:
        ticket = tickets.get(tid)
        if ticket is None:
            # Defensive — a tracking_log row could outlive its ticket; skip
            # rather than emit a half-populated entry.
            continue
        entries.append(
            {
                "ticket_id": tid,
                "ticket_key": ticket.ticket_key,
                "title": ticket.title,
                "tokens": tokens_by_ticket.get(tid, 0),
                "time_seconds": time_by_ticket.get(tid, 0),
            }
        )

    entries.sort(key=lambda r: (-r["tokens"], r["ticket_key"]))
    return entries


def compute_overhead_deltas(
    db: Session, session: DwbSession, *, now: datetime | None = None
) -> tuple[int, int]:
    """Return (tl_overhead_tokens, pm_overhead_tokens) for the session
    window: tracking_log overhead_token_report events partitioned by agent
    role (pm vs everything-else-counts-as-TL per DWB-305 invariant)."""
    win_start, win_end = compute_window(session, now=now)

    rows = db.execute(
        select(
            Agent.role,
            func.coalesce(func.sum(TrackingLog.tokens), 0).label("tokens"),
        )
        .join(Agent, TrackingLog.agent_id == Agent.id)
        .where(TrackingLog.project_id == session.project_id)
        .where(TrackingLog.event_type == "overhead_token_report")
        .where(TrackingLog.timestamp >= win_start)
        .where(TrackingLog.timestamp <= win_end)
        .group_by(Agent.role)
    ).all()

    tl = 0
    pm = 0
    for row in rows:
        if row.role == "pm":
            pm += int(row.tokens)
        else:
            tl += int(row.tokens)
    return tl, pm


def compute_live_totals(
    db: Session, session: DwbSession, *, now: datetime | None = None
) -> tuple[int, int]:
    """Compute live (total_tokens, total_time_seconds) for an open session.

    Tokens: sum of linked hook_sessions.total_tokens (same rollup logic
    `close_session` uses, kept private here so an open-session GET doesn't
    have to call close_session as a side effect).

    Time: wall clock from opened_at to `now` (or the window end). Closed
    sessions should just read the stored fields; this is the open path.
    """
    win_start, win_end = compute_window(session, now=now)

    tokens = db.execute(
        select(func.coalesce(func.sum(HookSession.total_tokens), 0)).where(
            HookSession.dwb_session_id == session.id
        )
    ).scalar()
    time_s = max(0, int((win_end - win_start).total_seconds()))
    return int(tokens or 0), time_s
