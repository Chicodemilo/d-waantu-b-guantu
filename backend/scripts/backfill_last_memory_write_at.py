#!/usr/bin/env python3
# Path: scripts/backfill_last_memory_write_at.py
# File: backfill_last_memory_write_at.py
# Created: 2026-09-16
# Purpose: One-shot idempotent backfill for DWB-564 - populate agents.last_memory_write_at for existing rows from their current memory.md, so it carries real history rather than starting sparse. Not required for the gate to work (memory_trace.agent_wrote_since also checks memory.md's mtime, which needs no backfill), but makes the column itself meaningful without waiting for the next write.
# Caller: Manual CLI (run once after `alembic upgrade head` lands dwb564a1b2c3)
# Callees: app.database.SessionLocal, app.models.agent.Agent, app.models.project.Project, app.services.memory_trace.latest_memory_write_at
# Data In: CLI args (--dry-run); agents/projects rows; each agent's memory.md on disk
# Data Out: stdout report; DB updates to agents.last_memory_write_at (when not --dry-run)
# Last Modified: 2026-09-16 (DWB-564)
"""One-shot DWB-564 backfill.

agents.last_memory_write_at (dwb564a1b2c3) is new and starts NULL for every
existing row. The write-on-close gate (memory_trace.agent_wrote_since) does
NOT need this backfill to work correctly - it also checks memory.md's own
mtime, which already reflects every agent's real history with no migration
step. This script exists so the COLUMN itself carries that same history
rather than staying sparse until each agent's next write through the API.

For each agent with a project_id and a project with a resolvable
repo_path, this reuses memory_trace.latest_memory_write_at - the original
ISO-heading scan - to read the newest heading currently in that agent's
memory.md, and writes it into last_memory_write_at. An agent with no
parseable heading (never wrote, or memory dir missing) is left NULL - that
IS the correct state, not a failure; the gate still has mtime to fall back
on for such an agent if their file exists but predates any heading-stamping
write.

Idempotent: safe to re-run. Each pass recomputes from current memory.md
state and overwrites, so a re-run after further writes picks up the latest
heading (though by then last_memory_write_at would usually already be
newer, since the write endpoints set it directly going forward).

Usage:
    python backend/scripts/backfill_last_memory_write_at.py             # apply
    python backend/scripts/backfill_last_memory_write_at.py --dry-run   # report only
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.agent import Agent
from app.models.project import Project
from app.services.memory_trace import latest_memory_write_at


def backfill(db: Session, dry_run: bool) -> dict:
    agents = db.scalars(select(Agent)).all()
    projects_by_id = {p.id: p for p in db.scalars(select(Project)).all()}

    total = len(agents)
    skipped_unscoped = 0
    skipped_no_repo = 0
    found = 0
    left_null = 0

    for agent in agents:
        project = projects_by_id.get(agent.project_id) if agent.project_id else None
        if project is None:
            skipped_unscoped += 1
            continue
        if not project.repo_path:
            skipped_no_repo += 1
            continue

        latest = latest_memory_write_at(project, agent)
        if latest is None:
            left_null += 1
            continue

        found += 1
        if not dry_run:
            agent.last_memory_write_at = latest

    if not dry_run:
        db.commit()

    return {
        "total_agents": total,
        "skipped_unscoped": skipped_unscoped,
        "skipped_no_repo_path": skipped_no_repo,
        "backfilled": found,
        "left_null_no_heading_found": left_null,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = backfill(db, dry_run=args.dry_run)
    finally:
        db.close()

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"DWB-564 backfill [{mode}]")
    for key, value in report.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
