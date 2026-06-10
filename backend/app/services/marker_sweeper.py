# Path: app/services/marker_sweeper.py
# File: marker_sweeper.py
# Created: 2026-06-10
# Purpose: Periodic sweep of stale .claude/agents/active/ marker files across all projects (DWB-369)
# Caller: app/services/marker_sweep_task.py (background asyncio loop), tests
# Callees: app.models.project, app.models.hook_session, filesystem
# Data In: SQLAlchemy Session, stale_minutes threshold
# Data Out: counts dict {projects, pending_removed, finalized_removed, skipped, errors}
# Last Modified: 2026-06-10

"""DWB-369: sweep stale session-marker files from every project's
``.claude/agents/active/`` directory.

The DWB-294 hook resolver relies on these marker files to bind a
SubagentStop's CC-assigned session_id to an agent_id. Lifecycle:

  1. TL pre-writes ``pending-<agent_id>-<unix_ms>-<rand4hex>`` before
     spawning a teammate.
  2. The teammate's first SubagentStop fires. The resolver atomically
     ``os.rename``s the pending- file to the SubagentStop's session_id.
  3. Subsequent SubagentStops with the same session_id hit the
     literal-named file directly.
  4. When the worker session ends cleanly, the marker is no longer
     needed but stays on disk - the resolver doesn't unlink it.

Two failure modes accumulate stale files:

  A. **Worker dies pre-SubagentStop** (CC ink-renderer crash pattern,
     see DWB-357). The ``pending-*`` file is never claimed. The
     existing in-handler lazy GC in ``_claim_pending_marker``
     (hook_tracking.py) only runs when ANOTHER SubagentStop scans the
     same dir, which never happens if no subagents ever finish cleanly
     on that project. CI accumulated 10 such files over two days.

  B. **Worker completes but the finalized marker lingers**. Once the
     hook_session is in ``completed`` status the marker has no further
     use. DWB accumulated 21 such files.

This sweeper handles both. Rules:

  - ``pending-*`` older than ``stale_minutes``: unlink unconditionally.
    The TL pre-writes these immediately before spawning; a worker that
    hasn't claimed its marker after 30+ minutes isn't coming back.

  - Anything else (finalized session_id-named file): unlink IFF the
    corresponding hook_session row is ``completed`` OR no hook_session
    exists at all. We deliberately preserve markers tied to an
    ``active`` hook_session because subsequent SubagentStops for that
    same session still need to look the marker up.

  - Files we can't categorize (parse errors, transient stat failures)
    are skipped, not deleted. The sweeper biases toward leaving files
    alone on uncertainty.

Returns a counts dict so the periodic task can log progress and tests
can assert exact numbers.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hook_session import HookSession, HookSessionStatus
from app.models.project import Project

logger = logging.getLogger(__name__)


# Source-of-truth pattern: matches hook_tracking._PENDING_MARKER_RE.
# Re-declared here (not imported) so this module has no dependency cycle
# back into hook_tracking.
_PENDING_MARKER_RE = re.compile(r"^pending-(\d+)-(\d+)-([0-9a-fA-F]{4})$")
_SESSION_MARKER_SUBPATH = ".claude/agents/active"


def sweep_stale_markers(
    db: Session,
    *,
    stale_minutes: int = 30,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Walk every project with a repo_path; sweep stale marker files.

    Returns::

        {
            "projects":           int,  # how many project dirs were scanned
            "pending_removed":    int,  # pending-* files unlinked (or would unlink)
            "finalized_removed":  int,  # session_id files unlinked (or would unlink)
            "preserved_active":   int,  # session_id files kept because hook_session is still active
            "skipped":            int,  # files we couldn't classify (parse/stat errors)
            "errors":             list, # {path, error} entries for non-fatal failures
        }

    ``dry_run=True`` reports the same counts without touching disk -
    useful for verifying the sweep target set before running for real.
    """
    out: dict[str, Any] = {
        "projects": 0,
        "pending_removed": 0,
        "finalized_removed": 0,
        "preserved_active": 0,
        "skipped": 0,
        "errors": [],
    }

    cutoff = time.time() - (stale_minutes * 60)
    projects = list(
        db.scalars(select(Project).where(Project.repo_path.isnot(None)))
    )

    for project in projects:
        marker_dir = Path(project.repo_path) / _SESSION_MARKER_SUBPATH
        if not marker_dir.is_dir():
            continue
        out["projects"] += 1

        try:
            entries = list(marker_dir.iterdir())
        except OSError as e:
            out["errors"].append({
                "project": project.prefix,
                "path": str(marker_dir),
                "error": f"{type(e).__name__}: {e}",
            })
            continue

        for entry in entries:
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                out["skipped"] += 1
                continue

            # Fresh enough: leave alone regardless of category.
            if mtime >= cutoff:
                continue

            is_pending = bool(_PENDING_MARKER_RE.match(entry.name))

            if is_pending:
                # Worker died pre-SubagentStop. Marker has no remaining
                # function - delete unconditionally past the threshold.
                if dry_run:
                    out["pending_removed"] += 1
                    continue
                try:
                    entry.unlink()
                    out["pending_removed"] += 1
                except OSError as e:
                    out["errors"].append({
                        "path": str(entry),
                        "error": f"{type(e).__name__}: {e}",
                    })
                continue

            # Finalized (session_id-named). Only remove if the backing
            # hook_session is completed - an active hook_session means a
            # subsequent SubagentStop may still need this marker. We
            # also remove if there is no hook_session at all (stale
            # marker from a dropped session).
            hook = db.scalar(
                select(HookSession)
                .where(HookSession.session_id == entry.name)
                .limit(1)
            )
            if hook is not None and hook.status == HookSessionStatus.active:
                out["preserved_active"] += 1
                continue

            if dry_run:
                out["finalized_removed"] += 1
                continue
            try:
                entry.unlink()
                out["finalized_removed"] += 1
            except OSError as e:
                out["errors"].append({
                    "path": str(entry),
                    "error": f"{type(e).__name__}: {e}",
                })

    return out
