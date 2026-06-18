#!/usr/bin/env python3
# Path: scripts/backfill_dwb_373.py
# File: backfill_dwb_373.py
# Created: 2026-06-12
# Purpose: One-shot idempotent backfill for DWB-373 - populate Ticket.completed_at and HookSession.dwb_session_id from existing rows so historical sessions list rows render correct tickets_completed and total_tokens
# Caller: Manual CLI (one-shot data fix)
# Callees: app.database.SessionLocal, app.models (Ticket, StatusHistory, HookSession, DwbSession)
# Data In: CLI args (--dry-run, --skip-a1, --skip-a2)
# Data Out: stdout report; DB updates (when not --dry-run)
# Last Modified: 2026-06-12
"""One-shot DWB-373 backfill.

Two columns existed in the schema but were never populated by production
code, so the sessions list (GET /api/projects/{id}/sessions) reported 0
for every row's tickets_completed and total_tokens:

  A1) tickets.completed_at  - PATCH-to-done never stamped it. Source of
      truth for the backfill: the latest StatusHistory row per ticket
      where new_status='done'. We use changed_at as completed_at.

  A2) hook_sessions.dwb_session_id - hook ingest never linked it. Source
      of truth: time-window join, hook_sessions.start_time falling inside
      [dwb_sessions.opened_at, COALESCE(dwb_sessions.closed_at, +inf)],
      same project. A hook_session that started mid-window attributes
      to that DWB session; a hook_session outside any window stays NULL.

  A2b) dwb_sessions.total_tokens - close_session freezes this at close
      time via _rollup_tokens (sum of linked hook_sessions). For closed
      DWB sessions that pre-date A2's linker, the frozen value was 0
      because no hook_sessions were linked. After A2 backfills the
      links, A2b refreshes the frozen total. Skipped for still-open
      sessions, which the list endpoint computes live.

The script is idempotent. Each backfill function filters on `col IS NULL`
or recomputes from current state, so re-running is a noop after the first
successful pass.

Usage:
    python backend/scripts/backfill_dwb_373.py             # apply all
    python backend/scripts/backfill_dwb_373.py --dry-run   # report only
    python backend/scripts/backfill_dwb_373.py --skip-a1   # skip A1
    python backend/scripts/backfill_dwb_373.py --skip-a2   # skip A2 + A2b
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.dwb_session import DwbSession
from app.models.hook_session import HookSession
from app.models.status_history import StatusHistory
from app.models.ticket import Ticket


def backfill_completed_at(db: Session, dry_run: bool) -> dict:
    """Populate Ticket.completed_at from the latest StatusHistory done-entry.

    Selects tickets with `completed_at IS NULL` and at least one
    StatusHistory row where new_status='done'. Uses the MAX(changed_at)
    per ticket so a ticket that bounced done -> in_progress -> done lands
    at the most recent done crossing (matches the runtime semantic that
    re-stamps on every done transition).

    Returns a dict of counts: total NULL-and-eligible, updated.
    """
    # candidates: ticket.id -> latest done changed_at
    rows = db.execute(
        select(
            StatusHistory.ticket_id,
            func.max(StatusHistory.changed_at).label("latest_done"),
        )
        .where(StatusHistory.new_status == "done")
        .group_by(StatusHistory.ticket_id)
    ).all()
    latest_done_by_ticket = {tid: ts for tid, ts in rows}

    eligible_ticket_ids = set(
        db.scalars(
            select(Ticket.id).where(Ticket.completed_at.is_(None))
        ).all()
    )

    targets = {
        tid: ts for tid, ts in latest_done_by_ticket.items() if tid in eligible_ticket_ids
    }

    if not dry_run and targets:
        for tid, ts in targets.items():
            db.execute(
                update(Ticket).where(Ticket.id == tid).values(completed_at=ts)
            )
        db.commit()

    return {
        "total_with_null_completed_at": len(eligible_ticket_ids),
        "eligible_via_status_history": len(targets),
        "updated": 0 if dry_run else len(targets),
        "remaining_null_no_history": len(eligible_ticket_ids) - len(targets),
    }


def backfill_hook_session_dwb_link(db: Session, dry_run: bool) -> dict:
    """Populate HookSession.dwb_session_id from time-window join.

    For each hook_session with NULL dwb_session_id, find the DWB session
    in the same project where hook_session.start_time falls inside
    [opened_at, COALESCE(closed_at, +inf)]. A hook_session that started
    outside any open window stays NULL (we don't speculate).

    Returns a dict of counts: total NULL, eligible (in some window),
    updated, remaining_null_outside_any_window.
    """
    null_hook_sessions = db.execute(
        select(HookSession.id, HookSession.project_id, HookSession.start_time)
        .where(HookSession.dwb_session_id.is_(None))
    ).all()

    # Pull all dwb_sessions once per project lookup to avoid per-row queries.
    dwb_rows = db.execute(
        select(DwbSession.id, DwbSession.project_id, DwbSession.opened_at, DwbSession.closed_at)
    ).all()
    dwb_by_project: dict[int, list[tuple]] = {}
    for did, pid, opened_at, closed_at in dwb_rows:
        dwb_by_project.setdefault(pid, []).append((did, opened_at, closed_at))

    updates: list[tuple[int, int]] = []  # (hook_session_id, dwb_session_id)
    eligible = 0
    for hs_id, hs_pid, hs_start in null_hook_sessions:
        if hs_start is None:
            continue
        for did, opened_at, closed_at in dwb_by_project.get(hs_pid, ()):
            if opened_at is None:
                continue
            if hs_start < opened_at:
                continue
            if closed_at is not None and hs_start > closed_at:
                continue
            updates.append((hs_id, did))
            eligible += 1
            break  # at most one DWB session can be active per project at a time

    if not dry_run and updates:
        for hs_id, did in updates:
            db.execute(
                update(HookSession).where(HookSession.id == hs_id).values(dwb_session_id=did)
            )
        db.commit()

    return {
        "total_with_null_dwb_session_id": len(null_hook_sessions),
        "eligible_via_time_window": eligible,
        "updated": 0 if dry_run else len(updates),
        "remaining_null_outside_any_window": len(null_hook_sessions) - eligible,
    }


def refresh_dwb_session_totals(db: Session, dry_run: bool) -> dict:
    """Recompute dwb_sessions.total_tokens for closed sessions from linked
    hook_sessions. The frozen value was set at close-time by close_session
    via _rollup_tokens, which sums hook_sessions where dwb_session_id =
    session.id. Sessions closed before A2's linker existed have frozen
    total_tokens=0 even though linked hook_sessions now exist.

    Open sessions (closed_at IS NULL) are skipped: the list endpoint
    computes their tokens live, no refresh needed.

    Idempotent: recomputes from current state every run; a no-op if the
    frozen value already matches the linked sum.
    """
    sessions = db.execute(
        select(DwbSession).where(DwbSession.closed_at.is_not(None))
    ).scalars().all()

    changed: list[tuple[int, int, int]] = []  # (id, old, new)
    for s in sessions:
        new_total = db.execute(
            select(func.coalesce(func.sum(HookSession.total_tokens), 0)).where(
                HookSession.dwb_session_id == s.id
            )
        ).scalar() or 0
        if new_total != s.total_tokens:
            changed.append((s.id, s.total_tokens, int(new_total)))
            if not dry_run:
                s.total_tokens = int(new_total)

    if not dry_run and changed:
        db.commit()

    return {
        "total_closed_sessions_scanned": len(sessions),
        "rows_with_drift": len(changed),
        "updated": 0 if dry_run else len(changed),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report counts, do not write")
    parser.add_argument("--skip-a1", action="store_true", help="skip Ticket.completed_at backfill")
    parser.add_argument("--skip-a2", action="store_true", help="skip HookSession.dwb_session_id + DwbSession.total_tokens refresh")
    args = parser.parse_args()

    with SessionLocal() as db:
        if not args.skip_a1:
            a1 = backfill_completed_at(db, dry_run=args.dry_run)
            print("A1 (Ticket.completed_at):", a1)
        if not args.skip_a2:
            a2 = backfill_hook_session_dwb_link(db, dry_run=args.dry_run)
            print("A2 (HookSession.dwb_session_id):", a2)
            a2b = refresh_dwb_session_totals(db, dry_run=args.dry_run)
            print("A2b (DwbSession.total_tokens refresh):", a2b)

    print("DONE." if not args.dry_run else "DRY-RUN COMPLETE.")


if __name__ == "__main__":
    main()
