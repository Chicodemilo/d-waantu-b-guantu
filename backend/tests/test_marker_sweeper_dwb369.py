# Path: tests/test_marker_sweeper_dwb369.py
# File: test_marker_sweeper_dwb369.py
# Created: 2026-06-10
# Purpose: Tests for DWB-369 marker sweeper - pending-* GC, finalized GC gated on hook_session status, end-to-end rename invariant preserved
# Caller: pytest
# Callees: app.services.marker_sweeper.sweep_stale_markers, app.services.hook_tracking.resolve_agent_from_marker
# Data In: tmp_path-rooted project repos, hand-rolled marker files + hook_session rows
# Data Out: Assertions on per-class removal counts, dry-run behavior, end-to-end pending->session_id rename still works
# Last Modified: 2026-06-10

"""DWB-369 coverage.

Two failure modes the sweeper closes:

  A. Worker dies pre-SubagentStop -> ``pending-*`` marker never claimed.
     Lazy in-handler GC only runs when ANOTHER SubagentStop fires for
     the same project; if no subagents ever finish on that project the
     files linger forever. CI accumulated 10 of these over two days.

  B. Worker completes cleanly but the finalized session_id-named marker
     is never garbage-collected. DWB accumulated 21 of these.

The sweeper handles both: pending-* past the stale window are unlinked
unconditionally; finalized files are unlinked iff the hook_session is
completed (or missing entirely) - never when active.

The resolver's existing rename behavior (pending-* -> session_id) must
keep working. End-to-end test exercises a fake SubagentStop against a
freshly-written pending- and asserts the rename still fires.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.services.marker_sweeper import sweep_stale_markers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_with_marker_dir(make_project, tmp_path):
    """Project rooted at tmp_path with an active marker dir created."""
    proj = make_project(repo_path=str(tmp_path))
    marker_dir = tmp_path / ".claude/agents/active"
    marker_dir.mkdir(parents=True, exist_ok=True)
    return proj, marker_dir


def _write_marker(
    marker_dir: Path,
    name: str,
    *,
    payload: dict | None = None,
    age_seconds: int = 0,
) -> Path:
    """Write a marker file with an optional payload + backdated mtime.

    age_seconds is how OLD the file should look - os.utime is set to
    `now - age_seconds`. 0 means brand new.
    """
    path = marker_dir / name
    path.write_text(
        json.dumps(payload or {"agent_id": 1, "agent_name": "x", "role": "x",
                                "project_prefix": "x"}),
        encoding="utf-8",
    )
    if age_seconds > 0:
        ts = time.time() - age_seconds
        os.utime(path, (ts, ts))
    return path


def _insert_hook_session(
    db_session,
    *,
    session_id: str,
    project_id: int,
    status: HookSessionStatus = HookSessionStatus.completed,
):
    row = HookSession(
        session_id=session_id,
        project_id=project_id,
        agent_id=None,
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow() if status == HookSessionStatus.completed else None,
        status=status,
        session_type=HookSessionType.teammate,
        total_tokens=0,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# 1. Pending-* removal: failure mode A
# ---------------------------------------------------------------------------


class TestPendingMarkerSweep:
    def test_stale_pending_removed(
        self, db_session, project_with_marker_dir,
    ):
        """A pending-* file older than stale_minutes is unlinked."""
        _, marker_dir = project_with_marker_dir
        stale = _write_marker(
            marker_dir, "pending-30-1780932872546-253a",
            age_seconds=60 * 60 * 24,  # 24 hours old
        )
        assert stale.exists()

        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["pending_removed"] == 1
        assert not stale.exists()

    def test_fresh_pending_preserved(
        self, db_session, project_with_marker_dir,
    ):
        """A pending-* file younger than stale_minutes stays (worker
        might still spawn and claim it)."""
        _, marker_dir = project_with_marker_dir
        fresh = _write_marker(
            marker_dir, "pending-31-1780935156559-efca",
            age_seconds=60,  # 1 minute old
        )
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["pending_removed"] == 0
        assert fresh.exists()

    def test_mixed_pending_ages_only_stale_removed(
        self, db_session, project_with_marker_dir,
    ):
        _, marker_dir = project_with_marker_dir
        stale = _write_marker(
            marker_dir, "pending-30-1780932872546-253a",
            age_seconds=60 * 60 * 48,
        )
        fresh = _write_marker(
            marker_dir, "pending-31-1781025910298-c5c0",
            age_seconds=60,
        )
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["pending_removed"] == 1
        assert not stale.exists()
        assert fresh.exists()


# ---------------------------------------------------------------------------
# 2. Finalized marker GC: gated on hook_session status
# ---------------------------------------------------------------------------


class TestFinalizedMarkerSweep:
    def test_finalized_with_completed_hook_session_removed(
        self, db_session, project_with_marker_dir,
    ):
        proj, marker_dir = project_with_marker_dir
        sid = "aab594e71c4185945"
        marker = _write_marker(marker_dir, sid, age_seconds=60 * 60 * 24)
        _insert_hook_session(
            db_session, session_id=sid, project_id=proj["id"],
            status=HookSessionStatus.completed,
        )
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["finalized_removed"] == 1
        assert not marker.exists()

    def test_finalized_with_no_hook_session_removed(
        self, db_session, project_with_marker_dir,
    ):
        """A marker with NO matching hook_session row is an orphan -
        safe to remove."""
        _, marker_dir = project_with_marker_dir
        marker = _write_marker(
            marker_dir, "orphan-session-id", age_seconds=60 * 60 * 24,
        )
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["finalized_removed"] == 1
        assert not marker.exists()

    def test_finalized_with_active_hook_session_preserved(
        self, db_session, project_with_marker_dir,
    ):
        """Active hook_session means the worker is still alive and
        subsequent SubagentStops may still need this marker - leave it."""
        proj, marker_dir = project_with_marker_dir
        sid = "active-session-abc"
        marker = _write_marker(marker_dir, sid, age_seconds=60 * 60 * 24)
        _insert_hook_session(
            db_session, session_id=sid, project_id=proj["id"],
            status=HookSessionStatus.active,
        )
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["preserved_active"] == 1
        assert out["finalized_removed"] == 0
        assert marker.exists()

    def test_finalized_fresh_preserved(
        self, db_session, project_with_marker_dir,
    ):
        """Even with a completed hook_session, a fresh marker stays
        until it ages past the threshold (gives concurrent activity
        room to breathe)."""
        proj, marker_dir = project_with_marker_dir
        sid = "fresh-completed-session"
        marker = _write_marker(marker_dir, sid, age_seconds=60)
        _insert_hook_session(
            db_session, session_id=sid, project_id=proj["id"],
            status=HookSessionStatus.completed,
        )
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["finalized_removed"] == 0
        assert marker.exists()


# ---------------------------------------------------------------------------
# 3. Counts + dry-run + multi-project + error handling
# ---------------------------------------------------------------------------


class TestSweepBookkeeping:
    def test_counts_dict_shape(
        self, db_session, project_with_marker_dir,
    ):
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert set(out.keys()) == {
            "projects", "pending_removed", "finalized_removed",
            "preserved_active", "skipped", "errors",
        }

    def test_dry_run_reports_without_unlinking(
        self, db_session, project_with_marker_dir,
    ):
        _, marker_dir = project_with_marker_dir
        marker = _write_marker(
            marker_dir, "pending-30-1780932872546-253a",
            age_seconds=60 * 60 * 24,
        )
        out = sweep_stale_markers(db_session, stale_minutes=30, dry_run=True)
        assert out["pending_removed"] == 1
        # File still exists - dry_run did not actually unlink.
        assert marker.exists()

    def test_walks_every_project_with_repo_path(
        self, db_session, make_project, tmp_path,
    ):
        """Two projects, each with a stale pending marker; one sweep
        cleans both."""
        a_root = tmp_path / "a"
        b_root = tmp_path / "b"
        (a_root / ".claude/agents/active").mkdir(parents=True)
        (b_root / ".claude/agents/active").mkdir(parents=True)
        make_project(repo_path=str(a_root))
        make_project(repo_path=str(b_root))

        _write_marker(
            a_root / ".claude/agents/active", "pending-1-1-aaaa",
            age_seconds=60 * 60 * 24,
        )
        _write_marker(
            b_root / ".claude/agents/active", "pending-2-2-bbbb",
            age_seconds=60 * 60 * 24,
        )

        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert out["pending_removed"] == 2
        assert out["projects"] >= 2

    def test_project_without_repo_path_skipped(
        self, db_session, make_project,
    ):
        """Project rows with repo_path=NULL are skipped (no dir to scan)."""
        make_project()  # no repo_path
        out = sweep_stale_markers(db_session, stale_minutes=30)
        # Should not raise; counts are zero for the no-repo project.
        assert out["pending_removed"] == 0
        assert out["finalized_removed"] == 0

    def test_unrelated_files_in_dir_left_alone_when_fresh(
        self, db_session, project_with_marker_dir,
    ):
        """A short-named file that doesn't match the pending regex AND
        is fresh-mtime stays untouched. Sweeper only acts on stale
        files."""
        _, marker_dir = project_with_marker_dir
        weird = _write_marker(
            marker_dir, "barry-s60-1780666493", age_seconds=60,
        )
        out = sweep_stale_markers(db_session, stale_minutes=30)
        assert weird.exists()
        assert out["finalized_removed"] == 0


# ---------------------------------------------------------------------------
# 4. End-to-end: pending-> session_id rename invariant preserved
# ---------------------------------------------------------------------------


class TestResolverInvariantUnaffected:
    """DWB-369 introduces a sweeper but must NOT regress the DWB-294
    resolver behavior: when a SubagentStop fires with a session_id and
    a freshly-written pending-* exists, the resolver still atomically
    renames the pending to the session_id."""

    def test_resolver_still_renames_pending_to_session_id(
        self, db_session, project_with_marker_dir, make_agent,
    ):
        from app.services.hook_tracking import resolve_agent_from_marker

        proj, marker_dir = project_with_marker_dir
        agent = make_agent(project_id=proj["id"])

        pending_name = f"pending-{agent['id']}-1234567890123-abcd"
        pending = _write_marker(
            marker_dir, pending_name,
            payload={
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "role": agent["role"],
                "project_prefix": proj["prefix"],
            },
            age_seconds=10,  # fresh
        )
        assert pending.exists()

        sid = "fresh-cc-session-uuid-1"
        from app.models.project import Project as ProjectModel
        project = db_session.get(ProjectModel, proj["id"])
        resolved = resolve_agent_from_marker(
            db_session, project, sid,
            hook_event="SubagentStop",
            hook_data={"session_id": sid, "hook_event_name": "SubagentStop"},
        )
        assert resolved is not None
        assert resolved.id == agent["id"]
        # Marker should be renamed from pending- to the session_id.
        assert not pending.exists()
        assert (marker_dir / sid).exists()
