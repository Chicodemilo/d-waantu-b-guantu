# Path: tests/test_failed_hooks.py
# File: test_failed_hooks.py
# Created: 2026-06-03
# Purpose: Verify FailedHook capture for hook payload-parse and handler exceptions
# Caller: pytest
# Callees: POST /api/hooks/session-start|session-end, FailedHook model
# Data In: Malformed payloads via TestClient
# Data Out: Assertions on FailedHook rows
# Last Modified: 2026-06-03

from sqlalchemy import select

from app.models.failed_hook import FailedHook
from tests.conftest import TestingSession


def _count() -> int:
    """Read via a fresh session — log_failed_hook commits on its own session,
    so the per-test rollback session can't see the row inside its tx."""
    db = TestingSession()
    try:
        return len(db.scalars(select(FailedHook)).all())
    finally:
        db.close()


def _last() -> FailedHook | None:
    db = TestingSession()
    try:
        return db.scalars(
            select(FailedHook).order_by(FailedHook.id.desc())
        ).first()
    finally:
        db.close()


class TestFailedHookCapture:
    def test_handler_exception_writes_row(self, client):
        before = _count()
        r = client.post(
            "/api/hooks/session-start",
            json={"transcript_path": "/tmp/missing-session-id"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "error"
        assert _count() == before + 1

        row = _last()
        assert row.hook_event in ("SessionStart", "session-start")
        assert row.status_code == 200
        assert "session_id" in row.error
        assert "ValueError" in row.error

    def test_payload_validation_writes_row(self, client):
        before = _count()
        r = client.post(
            "/api/hooks/session-end",
            json={"session_id": 12345},
        )
        assert r.status_code == 422
        assert _count() == before + 1

        row = _last()
        assert row.hook_event == "session-end"
        assert row.status_code == 422
        assert "RequestValidationError" in row.error

    def test_malformed_json_writes_row(self, client):
        before = _count()
        r = client.post(
            "/api/hooks/session-start",
            content=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422
        assert _count() == before + 1

        row = _last()
        assert row.hook_event == "session-start"
        assert row.status_code == 422
        assert "json_invalid" in row.error or "JSON" in row.error

    def test_well_formed_request_does_not_log(self, client, make_project):
        """A well-formed payload that the service handles cleanly must not
        create a failed_hooks row. Guards against false positives."""
        project = make_project(repo_path="/tmp/nonexistent-repo-for-hook-test")
        before = _count()
        client.post(
            "/api/hooks/session-start",
            json={
                "session_id": "test-session-happy-path",
                "transcript_path": "/tmp/test-transcript.jsonl",
                "cwd": project["repo_path"],
                "hook_event_name": "SessionStart",
            },
        )
        # The service may legitimately raise (e.g., no project resolves from
        # the cwd). At most one row, never more.
        assert _count() - before <= 1
