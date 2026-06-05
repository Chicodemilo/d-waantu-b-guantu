# Path: tests/test_hook_session_marker.py
# File: test_hook_session_marker.py
# Created: 2026-06-03
# Purpose: Tests for hook backend session-marker attribution (DWB-294)
# Caller: pytest
# Callees: POST /api/hooks/session-start, resolve_agent_from_marker
# Data In: Filesystem marker files at <repo>/.claude/agents/active/<session_id>
# Data Out: Assertions on attributed agent_id and failed_hooks rows
# Last Modified: 2026-06-03

import json
import uuid

from sqlalchemy import select

from app.models.failed_hook import FailedHook
from tests.conftest import TestingSession


def _failed_hooks_count() -> int:
    db = TestingSession()
    try:
        return len(db.scalars(select(FailedHook)).all())
    finally:
        db.close()


def _last_failed_hook() -> FailedHook | None:
    db = TestingSession()
    try:
        return db.scalars(
            select(FailedHook).order_by(FailedHook.id.desc())
        ).first()
    finally:
        db.close()


def _write_marker(repo_path, session_id, *, payload):
    marker_dir = repo_path / ".claude" / "agents" / "active"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / session_id).write_text(json.dumps(payload), encoding="utf-8")


class TestMarkerAttribution:
    def test_marker_attributes_to_named_agent(self, client, tmp_path, make_project):
        project = make_project(repo_path=str(tmp_path))
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Pixel",
            "role": "frontend-worker", "api_key": "marker-pixel",
        }).json()
        session_id = f"marker-{uuid.uuid4()}"
        _write_marker(tmp_path, session_id, payload={"agent_id": agent["id"]})

        r = client.post("/api/hooks/session-start", json={
            "session_id": session_id,
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
            # Deliberately wrong agent_name in the hook to prove marker wins
            "agent_name": "wrong-agent",
        })
        assert r.status_code == 200
        sessions = client.get(f"/api/hooks/sessions?project_id={project['id']}").json()
        ours = [s for s in sessions if s["session_id"] == session_id]
        assert len(ours) == 1
        assert ours[0]["agent_id"] == agent["id"]

    def test_missing_marker_logs_failed_hook_then_falls_back(self, client, tmp_path, make_project):
        """When marker is absent, log failed_hook and fall back to the existing
        agent_name resolve. The session still gets created via the fallback."""
        project = make_project(repo_path=str(tmp_path))
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Sage",
            "role": "tester", "api_key": "marker-sage",
        }).json()
        # legacy resolve_agent filters via project_agents join table; agents.project_id
        # alone isn't enough until that function is updated in a later ticket.
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": agent["id"],
        })
        before = _failed_hooks_count()
        session_id = f"no-marker-{uuid.uuid4()}"

        r = client.post("/api/hooks/session-start", json={
            "session_id": session_id,
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
            "agent_name": "tester",  # legacy role-based resolve hits this
        })
        assert r.status_code == 200
        after = _failed_hooks_count()
        assert after >= before + 1
        row = _last_failed_hook()
        assert "marker_missing" in row.error
        assert "SessionStart" in (row.hook_event or "")

        # Fallback still picked up the role-based agent
        sessions = client.get(f"/api/hooks/sessions?project_id={project['id']}").json()
        ours = [s for s in sessions if s["session_id"] == session_id]
        assert ours
        assert ours[0]["agent_id"] == agent["id"]

    def test_unparseable_marker_logs_failed_hook(self, client, tmp_path, make_project):
        project = make_project(repo_path=str(tmp_path))
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Pam",
            "role": "pm", "api_key": "marker-pam-bad",
        })
        session_id = f"bad-marker-{uuid.uuid4()}"
        # Write garbage instead of valid JSON
        marker_dir = tmp_path / ".claude" / "agents" / "active"
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / session_id).write_text("{not-json", encoding="utf-8")

        before = _failed_hooks_count()
        client.post("/api/hooks/session-start", json={
            "session_id": session_id,
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
            "agent_name": "pm",
        })
        assert _failed_hooks_count() >= before + 1
        row = _last_failed_hook()
        assert "marker_unparseable" in row.error

    def test_marker_agent_id_unknown_logs_failed_hook(self, client, tmp_path, make_project):
        project = make_project(repo_path=str(tmp_path))
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Devin",
            "role": "backend-worker", "api_key": "marker-devin-unknown",
        })
        session_id = f"unknown-{uuid.uuid4()}"
        _write_marker(tmp_path, session_id, payload={"agent_id": 999999})

        before = _failed_hooks_count()
        client.post("/api/hooks/session-start", json={
            "session_id": session_id,
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
            "agent_name": "backend-worker",
        })
        assert _failed_hooks_count() >= before + 1
        row = _last_failed_hook()
        assert "marker_agent_unknown" in row.error

    def test_marker_project_mismatch_logs_failed_hook(self, client, tmp_path, make_project):
        """An agent_id from a different project's marker is rejected."""
        proj_a = make_project(repo_path=str(tmp_path / "a"))
        proj_b = make_project(repo_path=str(tmp_path / "b"))
        (tmp_path / "a").mkdir(exist_ok=True)
        (tmp_path / "b").mkdir(exist_ok=True)

        agent_b = client.post("/api/agents", json={
            "project_id": proj_b["id"], "name": "Pixel",
            "role": "frontend-worker", "api_key": "marker-pixel-b",
        }).json()
        session_id = f"mismatch-{uuid.uuid4()}"
        # cwd is project A, but the marker points at project B's agent
        _write_marker(tmp_path / "a", session_id, payload={"agent_id": agent_b["id"]})

        before = _failed_hooks_count()
        client.post("/api/hooks/session-start", json={
            "session_id": session_id,
            "cwd": str(tmp_path / "a"),
            "hook_event_name": "SessionStart",
            "agent_name": "frontend-worker",
        })
        assert _failed_hooks_count() >= before + 1
        row = _last_failed_hook()
        assert "marker_project_mismatch" in row.error
