#!/usr/bin/env python3
# Path: scripts/cleanup_team_dirs.py
# File: cleanup_team_dirs.py
# Created: 2026-06-12
# Purpose: List + safely clean stale ~/.claude/teams/ and ~/.claude/tasks/ dirs that linger after team shutdown (DWB-389). Listing-only by default; --clean is a dry-run preview; --execute must be combined with --clean to actually unlink. Live-team guard: never touch a dir whose mtime is within --live-threshold-minutes of now.
# Caller: Manual CLI; tests/test_cleanup_team_dirs.py
# Callees: pathlib, argparse, stdout
# Data In: CLI args (--clean, --execute, --age-days, --live-threshold-minutes, --teams-root, --tasks-root)
# Data Out: stdout table; rm of stale dirs only when --clean --execute is set AND live-team guard passes
# Last Modified: 2026-06-12
"""Stale team-dir cleanup tooling.

Old ~/.claude/teams/ and ~/.claude/tasks/ subdirs accumulate when a team
shutdown does not unlink the dir on disk (UUID-named leftovers from
abandoned spawns, post-sprint teams whose Claude Code process was killed
without a clean teardown). These dirs mislead live-team liveness checks:
DWB-387 just landed last_seen + presumed_live, but the upstream attribution
chain still partly walks the filesystem in places, and stale dirs make a
parked-idle team look identical to a dead one.

This script gives operators (mostly the TL during sprint planning) a way
to see what is sitting there and prune the dead weight without ever
accidentally yanking a dir out from under a live team.

Modes
-----
  python cleanup_team_dirs.py                       # list both dirs, no actions
  python cleanup_team_dirs.py --age-days 7          # list only dirs older than 7d
  python cleanup_team_dirs.py --clean               # dry-run: prints what would be removed
  python cleanup_team_dirs.py --clean --execute     # actually unlink (with live guard)

Safety rails
------------
- Default mode is listing only. No --clean, no actions on disk.
- --clean alone is a dry-run preview. It walks the directories and prints
  what WOULD be removed plus what would be PROTECTED by the live-team
  guard, but never touches disk.
- --execute is only honored alongside --clean. Without --clean it is
  ignored. This avoids "I meant --clean --execute and typo'd to just
  --execute" footguns.
- Live-team guard: any dir whose mtime is within --live-threshold-minutes
  (default 60) of now is always protected from deletion, regardless of
  --age-days. The whole reason the guard exists is that a sub-hour mtime
  is a strong signal that some live process inside the dir is still
  writing to it.

Always exits 0 (per backend/scripts convention - operator tooling should
never propagate a hard failure that breaks a launcher upstream of it).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# Default live-team mtime guard. A team dir touched within the last hour
# is presumed-live and will never be deleted by --execute. Tunable from
# the CLI; reads cleanly as "an hour of mtime quiet means safe to clean".
DEFAULT_LIVE_THRESHOLD_MINUTES = 60

# Default roots. Both are user-level Claude Code state directories; the
# CLI overrides exist primarily for tests but also so an operator can
# point at a non-default checkout if they need to.
DEFAULT_TEAMS_ROOT = Path.home() / ".claude" / "teams"
DEFAULT_TASKS_ROOT = Path.home() / ".claude" / "tasks"


@dataclass
class DirRecord:
    path: Path
    kind: str           # "teams" or "tasks"
    age_seconds: float  # now - mtime
    member_count: int   # teammates (for teams) or task JSONs (for tasks)

    @property
    def age_days(self) -> float:
        return self.age_seconds / 86400.0

    def age_human(self) -> str:
        # Compact human-readable age suited to a single-column table cell.
        days = self.age_seconds / 86400
        if days >= 1:
            return f"{days:.1f}d"
        hours = self.age_seconds / 3600
        if hours >= 1:
            return f"{hours:.1f}h"
        minutes = self.age_seconds / 60
        return f"{minutes:.0f}m"


def _team_member_count(team_dir: Path) -> int:
    """Teammates a team dir is configured for.

    Each team has one inbox file per teammate in `inboxes/`. Some older
    leftover dirs are missing the inboxes subdir entirely; for those we
    fall back to the count of top-level non-dotfile entries so the column
    still tells the operator something non-zero when it should.
    """
    inboxes = team_dir / "inboxes"
    if inboxes.is_dir():
        try:
            return sum(1 for p in inboxes.iterdir() if not p.name.startswith("."))
        except OSError:
            return 0
    try:
        return sum(1 for p in team_dir.iterdir() if not p.name.startswith("."))
    except OSError:
        return 0


def _tasks_member_count(task_dir: Path) -> int:
    """Tasks inside a task dir. One JSON per task at top-level."""
    try:
        return sum(
            1 for p in task_dir.iterdir()
            if p.is_file() and p.suffix == ".json"
        )
    except OSError:
        return 0


def scan_root(
    root: Path, *, kind: str, now: float, age_days: float,
) -> list[DirRecord]:
    """Walk one root and return a record per top-level subdir.

    kind selects which member-counting strategy to use. age_days filters
    out subdirs whose mtime is newer than the threshold (0 disables the
    filter). The live-team guard is NOT applied here - that is a
    cleanup-time concern. Listing should always show everything that
    matches the operator's filter so they can decide what to do.
    """
    if not root.is_dir():
        return []

    records: list[DirRecord] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return []

    for entry in children:
        if not entry.is_dir():
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        age = now - mtime
        if age_days > 0 and age < age_days * 86400:
            continue
        members = (
            _team_member_count(entry) if kind == "teams"
            else _tasks_member_count(entry)
        )
        records.append(
            DirRecord(path=entry, kind=kind, age_seconds=age, member_count=members)
        )

    records.sort(key=lambda r: r.age_seconds, reverse=True)
    return records


def format_table(records: list[DirRecord]) -> str:
    """Render records as a fixed-column table.

    Empty record list returns the header alone so callers can still see
    that the script ran cleanly against an empty (or fully filtered) root.
    """
    header = f"{'KIND':<6} {'AGE':>8}  {'MEMBERS':>7}  PATH"
    if not records:
        return header + "\n  (no matching dirs)"
    lines = [header]
    for r in records:
        lines.append(
            f"{r.kind:<6} {r.age_human():>8}  {r.member_count:>7}  {r.path}"
        )
    return "\n".join(lines)


def plan_clean(
    records: list[DirRecord], *, live_threshold_minutes: int,
) -> tuple[list[DirRecord], list[DirRecord]]:
    """Split records into (to_remove, protected) based on the live-team guard.

    A dir whose mtime is within live_threshold_minutes of now is presumed
    live and goes to `protected` regardless of other filters. Everything
    else is a removal candidate.
    """
    threshold_seconds = live_threshold_minutes * 60
    to_remove: list[DirRecord] = []
    protected: list[DirRecord] = []
    for r in records:
        if r.age_seconds < threshold_seconds:
            protected.append(r)
        else:
            to_remove.append(r)
    return to_remove, protected


def run_clean(
    to_remove: list[DirRecord], *, execute: bool, log,
) -> tuple[int, int]:
    """Execute or dry-run the removals.

    Returns (removed_count, error_count). Errors are logged but never
    raised - operator tooling exits 0 (see module docstring).
    """
    removed = 0
    errors = 0
    for r in to_remove:
        if not execute:
            log(f"  WOULD REMOVE  {r.kind:<6} age={r.age_human():>6}  {r.path}")
            continue
        try:
            shutil.rmtree(r.path)
            removed += 1
            log(f"  REMOVED       {r.kind:<6} age={r.age_human():>6}  {r.path}")
        except OSError as e:
            errors += 1
            log(f"  ERROR         {r.kind:<6}  {r.path}  ({type(e).__name__}: {e})")
    return removed, errors


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cleanup_team_dirs.py",
        description=(
            "List and (optionally) clean stale ~/.claude/teams/ and "
            "~/.claude/tasks/ dirs. Listing-only by default. --clean is a "
            "dry-run preview; --clean --execute actually unlinks. "
            "Live-team guard always protects dirs touched within "
            "--live-threshold-minutes."
        ),
    )
    p.add_argument(
        "--clean", action="store_true",
        help="Show what would be cleaned. Dry-run unless --execute is also set.",
    )
    p.add_argument(
        "--execute", action="store_true",
        help="With --clean, actually unlink stale dirs. Ignored without --clean.",
    )
    p.add_argument(
        "--age-days", type=float, default=0.0,
        help="Only consider dirs whose mtime is older than this many days.",
    )
    p.add_argument(
        "--live-threshold-minutes", type=int,
        default=DEFAULT_LIVE_THRESHOLD_MINUTES,
        help=(
            "mtime within this many minutes of now is treated as live and "
            f"always protected from --execute (default {DEFAULT_LIVE_THRESHOLD_MINUTES})."
        ),
    )
    p.add_argument(
        "--teams-root", type=Path, default=DEFAULT_TEAMS_ROOT,
        help="Override the ~/.claude/teams/ root (testing/operator hook).",
    )
    p.add_argument(
        "--tasks-root", type=Path, default=DEFAULT_TASKS_ROOT,
        help="Override the ~/.claude/tasks/ root (testing/operator hook).",
    )
    return p


def main(argv: list[str] | None = None, *, _now: float | None = None) -> int:
    """Entry point.

    `_now` is a test-injection hook for deterministic age math; production
    callers leave it None and the function uses time.time().
    """
    args = build_parser().parse_args(argv)
    now = _now if _now is not None else time.time()

    teams = scan_root(
        args.teams_root, kind="teams", now=now, age_days=args.age_days,
    )
    tasks = scan_root(
        args.tasks_root, kind="tasks", now=now, age_days=args.age_days,
    )
    all_records = teams + tasks

    print(f"Scanned teams root: {args.teams_root}")
    print(f"Scanned tasks root: {args.tasks_root}")
    if args.age_days > 0:
        print(f"Filter: mtime older than {args.age_days} days")
    print()
    print(format_table(all_records))

    if not args.clean:
        return 0

    to_remove, protected = plan_clean(
        all_records, live_threshold_minutes=args.live_threshold_minutes,
    )

    print()
    print(
        f"--- clean plan (live-threshold={args.live_threshold_minutes}m, "
        f"execute={args.execute}) ---"
    )
    if protected:
        print(f"PROTECTED ({len(protected)}): live-team guard, mtime too recent")
        for r in protected:
            print(f"  KEEP          {r.kind:<6} age={r.age_human():>6}  {r.path}")
    if not to_remove:
        print("No removal candidates.")
        return 0

    removed, errors = run_clean(to_remove, execute=args.execute, log=print)
    print()
    if args.execute:
        print(f"Done. Removed {removed} dirs, {errors} error(s).")
    else:
        print(
            f"Dry-run. Would remove {len(to_remove)} dirs. "
            "Re-run with --clean --execute to actually unlink."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    # Per backend/scripts convention: catch everything, exit 0.
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"cleanup_team_dirs error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(0)
