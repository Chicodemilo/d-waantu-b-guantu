# Path: app/services/dwb_session_rollup.py
# File: dwb_session_rollup.py
# Created: 2026-06-09
# Purpose: Read-only rollups (by_role, by_ticket, overhead deltas) for DWB session detail endpoint (DWB-338) + list aggregates (DWB-346) + ad_hoc bucket (DWB-353)
# Caller: app/routers/dwb_sessions.py
# Callees: app.models.hook_session, app.models.tracking_log, app.models.agent, app.models.ticket
# Data In: SQLAlchemy Session + DwbSession instance
# Data Out: list[dict] for by_role / by_ticket, tuple[int,int] for overhead, tuple[int,int] for live totals
# Last Modified: 2026-06-10 (DWB-353)

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
from app.models.epic import Epic
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


# ---------------------------------------------------------------------------
# DWB-346: list-row aggregates
# ---------------------------------------------------------------------------


def compute_list_aggregates(
    db: Session, session: DwbSession, *, now: datetime | None = None
) -> dict:
    """Per-row aggregates for GET /api/projects/{id}/sessions.

    Returns a dict with five integer/string fields the list endpoint folds
    onto every DwbSessionListItem. Kept here (not inline in the router) so
    the SQL can evolve without churning the HTTP layer:

      tickets_made:      count of tickets in this project whose created_at
                          falls in [opened_at, window_end].
      tickets_completed: count of tickets whose completed_at falls in the
                          same window. Note we filter on the timestamp
                          column, not status, so a ticket that was completed
                          inside the window but reopened later still counts
                          for this session.
      agents_active:     distinct agent_id count from hook_sessions linked
                          to this DWB session (dwb_session_id = session.id).
                          We deliberately do NOT fall back to project-wide
                          hook_sessions here: agents that ran outside the
                          DWB session window should not inflate this number.
                          A NULL agent_id (hook_session not yet attributed)
                          is excluded by the IS NOT NULL filter.
      ticket_summary:    auto-derived "Epic Name (N)" string built from the
                          completed-in-window tickets. The dominant epic
                          wins (most tickets done in this session; ties
                          broken by epic.id asc for determinism). None when
                          no ticket completed in the window or none of the
                          completed tickets have an epic.

    The window end is the session's closed_at if closed, else `now` (or
    server utcnow if `now` is omitted) - same convention as compute_window.
    """
    win_start, win_end = compute_window(session, now=now)

    # tickets_made: project-scoped count, created in window.
    tickets_made = db.execute(
        select(func.count(Ticket.id))
        .where(Ticket.project_id == session.project_id)
        .where(Ticket.created_at >= win_start)
        .where(Ticket.created_at <= win_end)
    ).scalar() or 0

    # Pull the completed-in-window tickets once so we can both count them
    # and derive ticket_summary without re-querying.
    completed_rows = list(
        db.execute(
            select(Ticket.id, Ticket.epic_id)
            .where(Ticket.project_id == session.project_id)
            .where(Ticket.completed_at.isnot(None))
            .where(Ticket.completed_at >= win_start)
            .where(Ticket.completed_at <= win_end)
        ).all()
    )
    tickets_completed = len(completed_rows)

    # agents_active: distinct agent_id over linked hook_sessions only.
    agents_active = db.execute(
        select(func.count(func.distinct(HookSession.agent_id)))
        .where(HookSession.dwb_session_id == session.id)
        .where(HookSession.agent_id.isnot(None))
    ).scalar() or 0

    # ticket_summary: dominant epic among completed-in-window tickets.
    ticket_summary: str | None = None
    if completed_rows:
        # Group by epic_id (None bucket allowed but skipped in summary).
        per_epic: dict[int | None, int] = {}
        for _tid, epic_id in completed_rows:
            per_epic[epic_id] = per_epic.get(epic_id, 0) + 1
        # Drop the no-epic bucket - we cannot render a name for it. If the
        # only completed tickets are unaffiliated, ticket_summary stays None.
        per_epic_with_name = {
            eid: cnt for eid, cnt in per_epic.items() if eid is not None
        }
        if per_epic_with_name:
            # Pick dominant epic: most done, tiebreak by epic_id asc.
            dominant_epic_id = max(
                per_epic_with_name.keys(),
                key=lambda eid: (per_epic_with_name[eid], -eid),
            )
            epic = db.get(Epic, dominant_epic_id)
            if epic is not None:
                ticket_summary = f"{epic.name} ({per_epic_with_name[dominant_epic_id]})"

    # Note: aggregates use completed_at (the timestamp) rather than
    # TicketStatus.done so a later reopen/close churn does not move
    # historical session rollups. The session window is the truth.
    return {
        "tickets_made": int(tickets_made),
        "tickets_completed": int(tickets_completed),
        "agents_active": int(agents_active),
        "ticket_summary": ticket_summary,
    }


# ---------------------------------------------------------------------------
# DWB-353: ad_hoc bucket (worker-without-ticket overhead)
# ---------------------------------------------------------------------------


def compute_ad_hoc_bucket(
    db: Session, session: DwbSession, *, now: datetime | None = None
) -> tuple[int, int]:
    """Return (tokens, seconds) for the ad_hoc bucket inside the session window.

    The ad_hoc bucket holds work by non-TL/PM agents who ran without a
    ticket attribution in the window: real work that the skip-ticket-
    overhead lane (memory rule, by design) doesn't want paged on, but that
    must still surface in the dashboard so the human sees where their
    tokens went.

    tokens: sum of tracking_log.tokens where event_type='ad_hoc_token_report'
            inside the window for this project. The DWB-353 ingest path
            (hook_tracking handle_session_end + handle_subagent_stop) writes
            these events when a non-overhead-role agent's session lacks a
            ticket_id, so the rollup here is a direct sum.

    seconds: wall-clock from hook_sessions that match the same shape
             (worker role, no ticket_id, inside the window). Mirrors the
             hook-clamp convention compute_by_role uses so the units stay
             consistent across the response. Sessions that started before
             win_start or are still running at win_end are clamped to the
             window edges; disjoint sessions contribute 0.
    """
    win_start, win_end = compute_window(session, now=now)

    tokens = db.execute(
        select(func.coalesce(func.sum(TrackingLog.tokens), 0))
        .where(TrackingLog.project_id == session.project_id)
        .where(TrackingLog.event_type == "ad_hoc_token_report")
        .where(TrackingLog.timestamp >= win_start)
        .where(TrackingLog.timestamp <= win_end)
    ).scalar() or 0

    # For seconds: join hook_sessions to agents, filter by worker role +
    # null ticket_id, clamp wall clock to the window.
    rows = db.execute(
        select(HookSession.start_time, HookSession.end_time, Agent.role)
        .join(Agent, HookSession.agent_id == Agent.id)
        .where(HookSession.project_id == session.project_id)
        .where(HookSession.ticket_id.is_(None))
        .where(HookSession.start_time <= win_end)
        .where(
            (HookSession.end_time.is_(None))
            | (HookSession.end_time >= win_start)
        )
    ).all()

    total_seconds = 0
    for start_time, end_time, role in rows:
        if role in ("pm", "team-lead", "team_lead"):
            continue
        effective_end = end_time if end_time is not None else win_end
        total_seconds += _clamp_duration(
            start_time, effective_end, win_start, win_end
        )

    return int(tokens), int(total_seconds)
