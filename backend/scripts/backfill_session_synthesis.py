#!/usr/bin/env python3
# Path: backend/scripts/backfill_session_synthesis.py
# File: backfill_session_synthesis.py
# Created: 2026-06-25
# Purpose: One-shot, re-runnable backfill (DWB-485) that runs the close-time
#          session synthesizer over already-closed null-headline DWB sessions
#          (default 32/36/38) to populate headline + summary + weighted keywords
#          from their stored rollups. Reuses app.services.dwb_session._apply_synthesis
#          so a backfilled session is byte-identical to a live close. Idempotent:
#          _apply_synthesis clears prior entity_keywords rows before reinserting
#          and only synthesizes a headline when the existing one is null, so the
#          script is safe to run repeatedly. Always exits 0 (scripts convention).
# Caller: operator CLI (one-shot); tests/test_backfill_session_synthesis.py
# Callees: app.services.dwb_session._apply_synthesis, app.database.SessionLocal,
#          app.models.dwb_session.DwbSession
# Data In: optional --session-ids / --all-null-headline / --dry-run flags
# Data Out: prints a summary; returns a result dict from run_backfill()
# Last Modified: 2026-06-25

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Ensure backend/ is on sys.path so `python scripts/backfill_session_synthesis.py`
# works from any cwd (matches scripts/sync_instructions.py + backfill_dwb_373.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.dwb_session import DwbSession  # noqa: E402
from app.services.dwb_session import _apply_synthesis  # noqa: E402

# The null-headline closed DWB sessions named in DWB-485.
DEFAULT_SESSION_IDS: tuple[int, ...] = (32, 36, 38)


def _select_targets(
    db: Session,
    *,
    session_ids: list[int] | None,
    all_null_headline: bool,
    force: bool = False,
) -> tuple[list[DwbSession], list[dict]]:
    """Resolve which sessions to backfill.

    Returns (targets, skipped) where each skipped entry is {id, reason}. A valid
    target is a CLOSED session whose headline IS NULL. For an explicit id list
    we report why any requested id was skipped; for --all-null-headline we just
    sweep every closed null-headline session.

    `force` (DWB-499 re-synthesis): for the explicit-id path, also include
    already-headlined closed sessions so a re-run refreshes their summary +
    keywords (e.g. after a stopword change). _apply_synthesis preserves the
    existing headline and only rewrites summary/keywords, so a forced re-run is
    still non-destructive to a real close's headline.
    """
    if all_null_headline:
        targets = list(
            db.scalars(
                select(DwbSession)
                .where(DwbSession.headline.is_(None))
                .where(DwbSession.closed_at.isnot(None))
                .order_by(DwbSession.id)
            ).all()
        )
        return targets, []

    ids = session_ids if session_ids else list(DEFAULT_SESSION_IDS)
    targets: list[DwbSession] = []
    skipped: list[dict] = []
    for sid in ids:
        s = db.get(DwbSession, sid)
        if s is None:
            skipped.append({"id": sid, "reason": "not found"})
        elif s.closed_at is None:
            skipped.append({"id": sid, "reason": "still open"})
        elif s.headline is not None and not force:
            skipped.append({"id": sid, "reason": "already has headline"})
        else:
            targets.append(s)
    return targets, skipped


def run_backfill(
    db: Session,
    *,
    session_ids: list[int] | None = None,
    all_null_headline: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Backfill synthesis over the resolved target sessions.

    Flush-only (the caller owns the commit), mirroring the close path. For each
    target, calls _apply_synthesis with now=closed_at (closed sessions read their
    frozen window, so `now` is moot but a real datetime is required). A session
    counts as `populated` when its headline becomes non-null after synthesis;
    if the guarded synthesizer fails internally it leaves the row untouched and
    we record it under `failed` rather than crashing the batch.

    Returns a summary dict: {targeted, populated, failed, skipped, populated_ids}.
    """
    targets, skipped = _select_targets(
        db,
        session_ids=session_ids,
        all_null_headline=all_null_headline,
        force=force,
    )

    populated_ids: list[int] = []
    failed_ids: list[int] = []

    for s in targets:
        if dry_run:
            # Report intent only; touch nothing.
            populated_ids.append(s.id)
            continue
        now = s.closed_at or datetime.utcnow()
        _apply_synthesis(db, s, now=now)
        if s.headline is not None:
            populated_ids.append(s.id)
        else:
            failed_ids.append(s.id)

    return {
        "targeted": len(targets),
        "populated": len(populated_ids),
        "failed": len(failed_ids),
        "skipped": skipped,
        "populated_ids": populated_ids,
        "failed_ids": failed_ids,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill session synthesis over null-headline closed DWB sessions (DWB-485)."
    )
    parser.add_argument(
        "--session-ids",
        type=str,
        default=None,
        help="Comma-separated session ids to target (default: 32,36,38).",
    )
    parser.add_argument(
        "--all-null-headline",
        action="store_true",
        help="Sweep every closed session with a null headline (overrides --session-ids).",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Re-synthesize even sessions that already have a headline (refreshes "
        "summary + keywords, e.g. after a stopword change; headline preserved). "
        "Explicit-id path only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which sessions would be backfilled without writing.",
    )
    args = parser.parse_args(argv)

    session_ids: list[int] | None = None
    if args.session_ids:
        try:
            session_ids = [int(x) for x in args.session_ids.split(",") if x.strip()]
        except ValueError:
            print("Invalid --session-ids; expected comma-separated integers.")
            return 0  # scripts always exit 0

    db = SessionLocal()
    try:
        result = run_backfill(
            db,
            session_ids=session_ids,
            all_null_headline=args.all_null_headline,
            force=args.regenerate,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            db.commit()
        mode = "DRY RUN" if args.dry_run else "applied"
        print(f"[backfill_session_synthesis] {mode}")
        print(
            f"  targeted={result['targeted']} populated={result['populated']} "
            f"failed={result['failed']}"
        )
        if result["populated_ids"]:
            print(f"  populated ids: {result['populated_ids']}")
        if result["failed_ids"]:
            print(f"  failed ids:    {result['failed_ids']}")
        for sk in result["skipped"]:
            print(f"  skipped id={sk['id']}: {sk['reason']}")
    except Exception as exc:  # never block the operator; report and exit 0.
        try:
            db.rollback()
        except Exception:
            pass
        print(f"[backfill_session_synthesis] error (no changes committed): {exc}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
