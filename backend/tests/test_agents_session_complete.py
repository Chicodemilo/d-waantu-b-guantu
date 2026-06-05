# Path: tests/test_agents_session_complete.py
# File: test_agents_session_complete.py
# Created: 2026-06-03
# Purpose: Tests for POST /api/agents/{id}/session-complete (DWB-291)
# Caller: pytest
# Callees: POST /api/agents/{id}/session-complete
# Data In: Factory projects/agents, tmp_path filesystem
# Data Out: Assertions on scratchpad.md and recent_sessions.md contents
# Last Modified: 2026-06-03

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
        project, agent = _setup_agent(client, tmp_path)
        memory_dir = Path(tmp_path) / ".claude/agents/memory/SC1/Sage"
        # As of DWB-293, agent creation auto-scaffolds the memory_dir, so it
        # already exists by the time we hit session-complete. The scratchpad
        # is empty until the first append.

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
        assert any(p.endswith("/.claude/agents/memory/SC1/Sage/scratchpad.md") for p in body["paths_written"])
        assert any(p.endswith("/.claude/agents/memory/SC1/Sage/recent_sessions.md") for p in body["paths_written"])
        assert any(p.endswith("/.claude/agents/memory/SC1/Sage/lessons.md") for p in body["paths_written"])
        assert body["bytes_written"] > 0

        scratchpad = (memory_dir / "scratchpad.md").read_text()
        assert "session sess-abc-123" in scratchpad
        assert "summary: ran the golden test suite" in scratchpad
        assert "tokens_used: 12500" in scratchpad
        # lessons appear in both scratchpad (inline) and lessons.md (separate)
        assert "always reset DB between runs" in scratchpad
        assert "use fresh tmp_path" in scratchpad

        recent = (memory_dir / "recent_sessions.md").read_text()
        assert "sess-abc-123" in recent
        assert "(12500 tok)" in recent
        assert "ran the golden test suite" in recent

        lessons_md = (memory_dir / "lessons.md").read_text()
        assert "session sess-abc-123" in lessons_md
        assert "always reset DB between runs" in lessons_md
        assert "use fresh tmp_path" in lessons_md

    def test_appends_without_clobbering(self, client, tmp_path):
        project, agent = _setup_agent(client, tmp_path, prefix="SC2", name="Devin")
        for i in range(3):
            client.post(f"/api/agents/{agent['id']}/session-complete", json={
                "session_id": f"sess-{i}",
                "summary": f"iteration {i}",
            })
        scratchpad = (Path(tmp_path) / ".claude/agents/memory/SC2/Devin/scratchpad.md").read_text()
        assert scratchpad.count("session sess-") == 3
        recent = (Path(tmp_path) / ".claude/agents/memory/SC2/Devin/recent_sessions.md").read_text()
        assert len([ln for ln in recent.splitlines() if "sess-" in ln]) == 3

    def test_optional_fields_omitted_cleanly(self, client, tmp_path):
        project, agent = _setup_agent(client, tmp_path, prefix="SC3", name="Bolt")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-minimal",
            "summary": "no lessons, no tokens",
        })
        assert r.status_code == 200
        memory_dir = Path(tmp_path) / ".claude/agents/memory/SC3/Bolt"
        scratchpad = (memory_dir / "scratchpad.md").read_text()
        # When tokens_used omitted, no tokens line should appear
        assert "tokens_used" not in scratchpad
        # When lessons omitted, no lessons header
        assert "- lessons" not in scratchpad

        recent = (memory_dir / "recent_sessions.md").read_text()
        # No "(N tok)" annotation when tokens_used omitted
        assert " tok)" not in recent

        # lessons.md exists as a 0-byte placeholder (DWB-293 scaffolder pre-touches
        # all agent-owned files), but the endpoint must not have appended to it.
        assert (memory_dir / "lessons.md").stat().st_size == 0
        body = r.json()
        assert all(not p.endswith("/lessons.md") for p in body["paths_written"])

    def test_summary_with_newlines_collapsed_in_recent(self, client, tmp_path):
        project, agent = _setup_agent(client, tmp_path, prefix="SC4", name="Pam")
        client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-multiline",
            "summary": "line one\nline two\nline three",
        })
        recent = (Path(tmp_path) / ".claude/agents/memory/SC4/Pam/recent_sessions.md").read_text()
        # recent_sessions.md should be one line per entry — newlines collapsed
        lines = [ln for ln in recent.splitlines() if ln.startswith("- ")]
        assert len(lines) == 1
        assert "line one line two line three" in lines[0]


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
