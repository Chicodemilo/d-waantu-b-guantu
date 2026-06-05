# Path: tests/test_hook_orphan_sessions.py
# File: test_hook_orphan_sessions.py
# Created: 2026-06-03
# Purpose: Tests for GET /api/hooks/sessions?status=orphan (DWB-292)
# Caller: pytest
# Callees: GET /api/hooks/sessions
# Data In: Hand-rolled HookSession rows via the per-test db_session
# Data Out: Assertions on filter behavior and elapsed_seconds population
# Last Modified: 2026-06-03

from datetime import datetime, timedelta, timezone

import pytest

from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType


@pytest.fixture
def insert_hook_session(db_session):
    """Insert a HookSession via the per-test session so it shares the same
    transaction as project rows created via the test client. Without this,
    a fresh TestingSession() would block on FK locks waiting for the test's
    project row to commit (which never happens — tests roll back at teardown).
    """
    def _make(project_id, *, start_offset_minutes=0, status=HookSessionStatus.active, session_id):
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            start_time=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(minutes=start_offset_minutes),
            status=status,
            session_type=HookSessionType.teammate,
            total_tokens=0,
        )
        db_session.add(row)
        db_session.flush()  # makes the row visible without committing
        return row.id
    return _make


class TestOrphanFilter:
    def test_returns_active_sessions_older_than_cutoff(self, client, make_project, insert_hook_session):
        project = make_project()
        insert_hook_session(project["id"], start_offset_minutes=5, session_id="fresh-active")
        old_id = insert_hook_session(project["id"], start_offset_minutes=45, session_id="stale-active")

        r = client.get(f"/api/hooks/sessions?status=orphan&project_id={project['id']}")
        assert r.status_code == 200
        ids = [row["id"] for row in r.json()]
        assert old_id in ids
        assert all(row["status"] == "active" for row in r.json())

    def test_completed_sessions_never_orphan(self, client, make_project, insert_hook_session):
        project = make_project()
        insert_hook_session(
            project["id"], start_offset_minutes=120,
            status=HookSessionStatus.completed, session_id="old-but-done",
        )
        r = client.get(f"/api/hooks/sessions?status=orphan&project_id={project['id']}")
        assert all(row["status"] == "active" for row in r.json())

    def test_elapsed_seconds_populated_for_orphan_rows(self, client, make_project, insert_hook_session):
        project = make_project()
        insert_hook_session(
            project["id"], start_offset_minutes=60, session_id="elapsed-check",
        )
        r = client.get(f"/api/hooks/sessions?status=orphan&project_id={project['id']}")
        rows = r.json()
        assert rows
        for row in rows:
            assert row["elapsed_seconds"] is not None
            assert row["elapsed_seconds"] >= 60 * 30

    def test_cutoff_minutes_param_overrides_default(self, client, make_project, insert_hook_session):
        project = make_project()
        insert_hook_session(
            project["id"], start_offset_minutes=10, session_id="ten-min-old",
        )
        r = client.get(f"/api/hooks/sessions?status=orphan&project_id={project['id']}")
        assert r.json() == []
        r2 = client.get(
            f"/api/hooks/sessions?status=orphan&project_id={project['id']}&cutoff_minutes=5"
        )
        assert len(r2.json()) == 1

    def test_non_orphan_status_still_works(self, client, make_project, insert_hook_session):
        project = make_project()
        insert_hook_session(
            project["id"], start_offset_minutes=10,
            status=HookSessionStatus.completed, session_id="completed-row",
        )
        r = client.get(f"/api/hooks/sessions?status=completed&project_id={project['id']}")
        assert r.status_code == 200
        rows = r.json()
        assert rows
        assert all(row["status"] == "completed" for row in rows)
        assert all(row.get("elapsed_seconds") is None for row in rows)

    def test_invalid_status_returns_400(self, client):
        r = client.get("/api/hooks/sessions?status=nonsense")
        assert r.status_code == 400
        assert "invalid status" in r.json()["detail"]
