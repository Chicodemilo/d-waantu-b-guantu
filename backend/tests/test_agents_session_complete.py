# Path: tests/test_agents_session_complete.py
# File: test_agents_session_complete.py
# Created: 2026-06-03
# Purpose: Tests for POST /api/agents/{id}/session-complete (DWB-291)
# Caller: pytest
# Callees: POST /api/agents/{id}/session-complete
# Data In: Factory projects/agents, tmp_path filesystem
# Data Out: Assertions on memory.md contents (DWB-401 2-file model)
# Last Modified: 2026-06-19

import re
from pathlib import Path


def _setup_agent(client, tmp_path, prefix="SC1", name="Sage"):
    project = client.post("/api/projects", json={
        "prefix": prefix,
        "name": f"{prefix} Project",
        "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"],
        "name": name,
        "role": "tester",
        "api_key": f"{prefix}-{name}-key",
    }).json()
    return project, agent


class TestSessionCompleteWriting:
    def test_creates_memory_dir_and_appends(self, client, tmp_path):
        # DWB-401: session-complete writes ONE block to memory.md (summary +
        # tokens + lessons inline). No recent_sessions.md / lessons.md.
        project, agent = _setup_agent(client, tmp_path)
        memory_dir = Path(tmp_path) / ".dwb/memory/SC1/Sage"

        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-abc-123",
            "summary": "ran the golden test suite, all green",
            "lessons": ["always reset DB between runs", "use fresh tmp_path"],
            "tokens_used": 12500,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["agent_id"] == agent["id"]
        assert body["session_id"] == "sess-abc-123"
        # ISO 8601 with UTC offset (e.g., 2026-06-03T20:55:00+00:00)
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}", body["timestamp"])
        assert any(p.endswith("/.dwb/memory/SC1/Sage/memory.md") for p in body["paths_written"])
        assert all(not p.endswith(("scratchpad.md", "recent_sessions.md", "lessons.md")) for p in body["paths_written"])
        assert body["bytes_written"] > 0

        memory = (memory_dir / "memory.md").read_text()
        assert "session sess-abc-123" in memory
        assert "summary: ran the golden test suite" in memory
        assert "tokens_used: 12500" in memory
        # lessons fold into the single memory.md block
        assert "always reset DB between runs" in memory
        assert "use fresh tmp_path" in memory
        # Retired files are not created
        assert not (memory_dir / "recent_sessions.md").exists()
        assert not (memory_dir / "lessons.md").exists()

    def test_appends_without_clobbering(self, client, tmp_path):
        project, agent = _setup_agent(client, tmp_path, prefix="SC2", name="Devin")
        for i in range(3):
            client.post(f"/api/agents/{agent['id']}/session-complete", json={
                "session_id": f"sess-{i}",
                "summary": f"iteration {i}",
            })
        memory = (Path(tmp_path) / ".dwb/memory/SC2/Devin/memory.md").read_text()
        assert memory.count("session sess-") == 3

    def test_optional_fields_omitted_cleanly(self, client, tmp_path):
        project, agent = _setup_agent(client, tmp_path, prefix="SC3", name="Bolt")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-minimal",
            "summary": "no lessons, no tokens",
        })
        assert r.status_code == 200
        memory_dir = Path(tmp_path) / ".dwb/memory/SC3/Bolt"
        memory = (memory_dir / "memory.md").read_text()
        # When tokens_used omitted, no tokens line should appear
        assert "tokens_used" not in memory
        # When lessons omitted, no lessons header
        assert "- lessons" not in memory
        # Retired files never created
        assert not (memory_dir / "lessons.md").exists()
        assert not (memory_dir / "recent_sessions.md").exists()
        body = r.json()
        assert all(not p.endswith("/lessons.md") for p in body["paths_written"])

    def test_summary_with_newlines_in_memory_block(self, client, tmp_path):
        # DWB-401: the session block lands in memory.md (recent_sessions.md gone).
        project, agent = _setup_agent(client, tmp_path, prefix="SC4", name="Pam")
        client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-multiline",
            "summary": "line one\nline two\nline three",
        })
        memory = (Path(tmp_path) / ".dwb/memory/SC4/Pam/memory.md").read_text()
        assert "sess-multiline" in memory
        assert "line one" in memory and "line three" in memory


class TestSessionCompleteErrors:
    def test_404_when_agent_missing(self, client):
        r = client.post("/api/agents/999999/session-complete", json={
            "session_id": "sess-x", "summary": "n/a",
        })
        assert r.status_code == 404

    def test_404_when_agent_has_no_project_id(self, client, tmp_path):
        """An agent with NULL project_id can't resolve its memory_dir."""
        # We can't POST a NULL project_id (schema requires it); but the legacy
        # rows with NULL project_id exist in the prod DB (per DWB-287).
        # Simulate via a direct DB write through the test session.
        from app.models.agent import Agent
        from tests.conftest import TestingSession
        db = TestingSession()
        try:
            orphan = Agent(
                name="Orphan", role="tester",
                api_key="orphan-key-unique", is_active=True, project_id=None,
            )
            db.add(orphan)
            db.commit()
            db.refresh(orphan)
            orphan_id = orphan.id
        finally:
            db.close()

        r = client.post(f"/api/agents/{orphan_id}/session-complete", json={
            "session_id": "sess-orphan", "summary": "should 404",
        })
        assert r.status_code == 404
        assert "no project_id" in r.json()["detail"]
