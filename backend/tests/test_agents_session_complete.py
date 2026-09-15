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
        # DWB-401: session-complete writes ONE block to memory.md.
        # DWB-560: that block is LESSONS ONLY - no summary, no token count.
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
        # DWB-560: narration no longer reaches the file; the DB is the record.
        assert "summary" not in memory
        assert "ran the golden test suite" not in memory
        assert "12500" not in memory
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
                # DWB-560: only a wrap-up carrying lessons writes a block.
                "lessons": [f"lesson from iteration {i}"],
            })
        memory = (Path(tmp_path) / ".dwb/memory/SC2/Devin/memory.md").read_text()
        assert memory.count("session sess-") == 3

    def test_lessons_free_wrapup_writes_nothing(self, client, tmp_path):
        """DWB-560: with no lessons there is nothing durable to record, so the
        endpoint writes no block at all rather than a bare heading."""
        project, agent = _setup_agent(client, tmp_path, prefix="SC3", name="Bolt")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-minimal",
            "summary": "no lessons, no tokens",
        })
        assert r.status_code == 200
        memory_dir = Path(tmp_path) / ".dwb/memory/SC3/Bolt"
        memory = (memory_dir / "memory.md").read_text()
        assert memory.strip() == ""
        assert "sess-minimal" not in memory
        assert "tokens_used" not in memory
        assert "- lessons" not in memory
        # Retired files never created
        assert not (memory_dir / "lessons.md").exists()
        assert not (memory_dir / "recent_sessions.md").exists()
        body = r.json()
        assert body["paths_written"] == []
        assert body["bytes_written"] == 0

    def test_multiline_summary_never_reaches_the_file(self, client, tmp_path):
        """DWB-560: a multi-line summary used to be copied verbatim into the
        block. It is exactly the narration the ruling removed, so now only the
        lessons land and the summary stays in the request and the database."""
        project, agent = _setup_agent(client, tmp_path, prefix="SC4", name="Pam")
        client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-multiline",
            "summary": "line one\nline two\nline three",
            "lessons": ["the durable part"],
        })
        memory = (Path(tmp_path) / ".dwb/memory/SC4/Pam/memory.md").read_text()
        assert "sess-multiline" in memory
        assert "the durable part" in memory
        assert "line one" not in memory and "line three" not in memory


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
