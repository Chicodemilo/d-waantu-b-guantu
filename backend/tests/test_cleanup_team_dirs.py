# Path:          tests/test_cleanup_team_dirs.py
# File:          test_cleanup_team_dirs.py
# Created:       2026-06-12
# Purpose:       Unit tests for backend/scripts/cleanup_team_dirs.py (DWB-389)
# Caller:        pytest
# Callees:       scripts.cleanup_team_dirs (scan_root, plan_clean, run_clean, main)
# Data In:       tmp_path fixtures simulating ~/.claude/teams + ~/.claude/tasks
# Data Out:      Assertions on records, table output, protection, and disk effects
# Last Modified: 2026-06-12

"""Tests for cleanup_team_dirs.

Covers:
- scan_root member counting for both kinds.
- age-days filter.
- plan_clean live-team guard at the live-threshold-minutes boundary.
- run_clean dry-run vs execute on tmp_path so no real ~/.claude/ state moves.
- main() integration: --clean alone never deletes; --clean --execute does
  (subject to the live guard).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest


# Load the script as a module without putting backend/scripts on sys.path.
# Register in sys.modules before exec so @dataclass can resolve __module__.
_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "cleanup_team_dirs.py"
)
_spec = importlib.util.spec_from_file_location("cleanup_team_dirs", _SCRIPT_PATH)
ctd = importlib.util.module_from_spec(_spec)
sys.modules["cleanup_team_dirs"] = ctd
_spec.loader.exec_module(ctd)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _set_mtime(path: Path, *, seconds_ago: float) -> None:
    """Backdate a path's mtime to `seconds_ago` from now."""
    target = time.time() - seconds_ago
    os.utime(path, (target, target))


def _make_team(
    root: Path, name: str, *, members: list[str], age_seconds: float,
) -> Path:
    team = root / name
    team.mkdir(parents=True)
    inboxes = team / "inboxes"
    inboxes.mkdir()
    for m in members:
        (inboxes / f"{m}.json").write_text("{}")
    (team / "config.json").write_text(json.dumps({"team": name}))
    # mtime on the team dir itself, after all inner writes (which would
    # otherwise refresh it). Walk children first to age them consistently.
    _set_mtime(inboxes, seconds_ago=age_seconds)
    _set_mtime(team, seconds_ago=age_seconds)
    return team


def _make_task(
    root: Path, name: str, *, task_count: int, age_seconds: float,
) -> Path:
    task = root / name
    task.mkdir(parents=True)
    (task / ".lock").write_text("")
    for i in range(1, task_count + 1):
        (task / f"{i}.json").write_text("{}")
    _set_mtime(task, seconds_ago=age_seconds)
    return task


# ---------------------------------------------------------------------------
# scan_root
# ---------------------------------------------------------------------------

class TestScanRoot:
    def test_scan_returns_empty_for_missing_root(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        assert ctd.scan_root(
            missing, kind="teams", now=time.time(), age_days=0,
        ) == []

    def test_team_member_count_uses_inboxes(self, tmp_path):
        _make_team(
            tmp_path, "fraudi-s14",
            members=["Pam", "Archie", "Sylvie"], age_seconds=3600,
        )
        records = ctd.scan_root(
            tmp_path, kind="teams", now=time.time(), age_days=0,
        )
        assert len(records) == 1
        assert records[0].member_count == 3
        assert records[0].kind == "teams"

    def test_tasks_member_count_uses_top_level_jsons(self, tmp_path):
        _make_task(tmp_path, "uuid-abc", task_count=5, age_seconds=7200)
        records = ctd.scan_root(
            tmp_path, kind="tasks", now=time.time(), age_days=0,
        )
        assert len(records) == 1
        # 5 *.json files; .lock is excluded by suffix filter.
        assert records[0].member_count == 5

    def test_age_days_filter_excludes_recent_dirs(self, tmp_path):
        _make_team(tmp_path, "old", members=["A"], age_seconds=8 * 86400)
        _make_team(tmp_path, "new", members=["B"], age_seconds=1 * 3600)
        records = ctd.scan_root(
            tmp_path, kind="teams", now=time.time(), age_days=7,
        )
        names = [r.path.name for r in records]
        assert names == ["old"]

    def test_age_days_zero_disables_filter(self, tmp_path):
        _make_team(tmp_path, "fresh", members=["A"], age_seconds=60)
        records = ctd.scan_root(
            tmp_path, kind="teams", now=time.time(), age_days=0,
        )
        assert [r.path.name for r in records] == ["fresh"]


# ---------------------------------------------------------------------------
# plan_clean
# ---------------------------------------------------------------------------

class TestPlanClean:
    def test_recent_dirs_are_protected(self, tmp_path):
        _make_team(tmp_path, "live-team", members=["A"], age_seconds=600)  # 10m
        _make_team(tmp_path, "dead-team", members=["B"], age_seconds=86400)  # 1d
        records = ctd.scan_root(
            tmp_path, kind="teams", now=time.time(), age_days=0,
        )
        to_remove, protected = ctd.plan_clean(
            records, live_threshold_minutes=60,
        )
        assert {r.path.name for r in protected} == {"live-team"}
        assert {r.path.name for r in to_remove} == {"dead-team"}

    def test_zero_threshold_protects_nothing(self, tmp_path):
        _make_team(tmp_path, "just-touched", members=["A"], age_seconds=5)
        records = ctd.scan_root(
            tmp_path, kind="teams", now=time.time(), age_days=0,
        )
        to_remove, protected = ctd.plan_clean(
            records, live_threshold_minutes=0,
        )
        assert protected == []
        assert {r.path.name for r in to_remove} == {"just-touched"}


# ---------------------------------------------------------------------------
# run_clean
# ---------------------------------------------------------------------------

class TestRunClean:
    def test_dry_run_does_not_unlink(self, tmp_path):
        team = _make_team(tmp_path, "old", members=["A"], age_seconds=86400)
        records = ctd.scan_root(
            tmp_path, kind="teams", now=time.time(), age_days=0,
        )
        log_lines: list[str] = []
        removed, errors = ctd.run_clean(records, execute=False, log=log_lines.append)
        assert removed == 0
        assert errors == 0
        assert team.is_dir(), "dry-run must never touch disk"
        assert any("WOULD REMOVE" in line for line in log_lines)

    def test_execute_unlinks_directories(self, tmp_path):
        team = _make_team(tmp_path, "old", members=["A"], age_seconds=86400)
        records = ctd.scan_root(
            tmp_path, kind="teams", now=time.time(), age_days=0,
        )
        removed, errors = ctd.run_clean(records, execute=True, log=lambda _l: None)
        assert removed == 1
        assert errors == 0
        assert not team.exists()


# ---------------------------------------------------------------------------
# main() — integration
# ---------------------------------------------------------------------------

class TestMain:
    def test_default_mode_lists_without_actions(self, tmp_path, capsys):
        teams_root = tmp_path / "teams"
        tasks_root = tmp_path / "tasks"
        teams_root.mkdir()
        tasks_root.mkdir()
        team = _make_team(teams_root, "old", members=["A"], age_seconds=86400)
        task = _make_task(tasks_root, "uuid", task_count=2, age_seconds=86400)

        rc = ctd.main([
            "--teams-root", str(teams_root),
            "--tasks-root", str(tasks_root),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        # Both kinds rendered; nothing deleted in default mode.
        assert "teams" in out and "tasks" in out
        assert "old" in out and "uuid" in out
        assert "WOULD REMOVE" not in out
        assert team.is_dir() and task.is_dir()

    def test_clean_without_execute_is_dry_run(self, tmp_path, capsys):
        teams_root = tmp_path / "teams"
        teams_root.mkdir()
        team = _make_team(teams_root, "old", members=["A"], age_seconds=86400)

        rc = ctd.main([
            "--teams-root", str(teams_root),
            "--tasks-root", str(tmp_path / "absent"),
            "--clean",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "WOULD REMOVE" in out
        assert "Dry-run" in out
        assert team.is_dir(), "--clean alone must not unlink"

    def test_clean_execute_unlinks_stale_but_protects_live(self, tmp_path, capsys):
        teams_root = tmp_path / "teams"
        teams_root.mkdir()
        old = _make_team(teams_root, "old", members=["A"], age_seconds=86400)
        live = _make_team(teams_root, "live", members=["B"], age_seconds=600)

        rc = ctd.main([
            "--teams-root", str(teams_root),
            "--tasks-root", str(tmp_path / "absent"),
            "--clean", "--execute",
            "--live-threshold-minutes", "60",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "REMOVED" in out
        assert "PROTECTED" in out
        assert not old.exists(), "stale dir must be removed by --execute"
        assert live.is_dir(), "live-guard must keep the recently-touched dir"

    def test_execute_alone_without_clean_is_ignored(self, tmp_path, capsys):
        """--execute without --clean must be a no-op on disk.

        Avoids the footgun where someone types --execute meaning the
        full clean command but forgets --clean. Default mode prevails.
        """
        teams_root = tmp_path / "teams"
        teams_root.mkdir()
        team = _make_team(teams_root, "old", members=["A"], age_seconds=86400)

        rc = ctd.main([
            "--teams-root", str(teams_root),
            "--tasks-root", str(tmp_path / "absent"),
            "--execute",
        ])
        assert rc == 0
        assert team.is_dir(), "--execute without --clean must not act"
