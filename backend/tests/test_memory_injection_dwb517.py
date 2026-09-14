# Path: tests/test_memory_injection_dwb517.py
# File: test_memory_injection_dwb517.py
# Created: 2026-09-14 (DWB-517)
# Purpose: DWB-517 - forced (passive) memory read. (a) spawn-prepare returns the
#          agent's FULL memory.md as `memory_full`; (b) the SessionStart hook
#          injects the resolved project team-lead's full memory.md as
#          hookSpecificOutput.additionalContext. Both degrade to empty/no-inject
#          when the memory file is missing or empty.
# Caller: pytest
# Callees: POST /api/agents/spawn-prepare, POST /api/hooks/session-start
# Data In: Factory projects/agents with repo_path=tmp_path + written memory.md
# Data Out: Assertions on memory_full field + additionalContext injection
# Last Modified: 2026-09-14 (DWB-517)

import uuid


def _memory_path(tmp_path, prefix, name):
    d = tmp_path / ".dwb" / "memory" / prefix / name
    d.mkdir(parents=True, exist_ok=True)
    return d / "memory.md"


class TestSpawnPrepareMemoryFull:
    def test_memory_full_returns_whole_file(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "MF1", "name": "MemFull One", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Barrow",
            "role": "backend-worker", "api_key": "mf1-barrow",
        })
        body_text = (
            "# Memory - Barrow\n\n## 2026-09-01T10:00:00\nfirst entry\n\n"
            "## 2026-09-02T10:00:00\nsecond entry with detail\n"
        )
        _memory_path(tmp_path, "MF1", "Barrow").write_text(body_text)

        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Barrow", "project_prefix": "MF1",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        # Full file, verbatim - not just the tail excerpt.
        assert body["memory_full"] == body_text
        assert "first entry" in body["memory_full"]
        # Excerpt field still present for compat.
        assert body["scratchpad_excerpt"].startswith("## Recent Scratchpad")

    def test_memory_full_empty_when_no_memory(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "MF2", "name": "MemFull Two", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Blank",
            "role": "backend-worker", "api_key": "mf2-blank",
        })
        r = client.post("/api/agents/spawn-prepare", json={
            "role": "backend-worker", "name": "Blank", "project_prefix": "MF2",
        })
        assert r.status_code == 200, r.text
        # Fresh agent: scaffold creates an empty memory.md -> empty string.
        assert r.json()["memory_full"] == ""


class TestSessionStartInjectsTlMemory:
    def _project_with_tl(self, client, tmp_path, prefix):
        project = client.post("/api/projects", json={
            "prefix": prefix, "name": f"{prefix} proj", "repo_path": str(tmp_path),
        }).json()
        tl = client.post("/api/agents", json={
            "project_id": project["id"], "name": f"Archie_{prefix}",
            "role": "team-lead", "api_key": f"{prefix}-tl",
        }).json()
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": tl["id"],
        })
        return project, tl

    def test_tl_memory_injected_as_additional_context(self, client, tmp_path):
        project, tl = self._project_with_tl(client, tmp_path, "INJ")
        tl_mem = "# Memory - Archie_INJ\n\n## 2026-09-10T09:00:00\nsprint state notes\n"
        _memory_path(tmp_path, "INJ", tl["name"]).write_text(tl_mem)

        r = client.post("/api/hooks/session-start", json={
            "session_id": str(uuid.uuid4()),
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        hso = body["hookSpecificOutput"]
        assert hso["hookEventName"] == "SessionStart"
        assert hso["additionalContext"] == tl_mem

    def test_no_injection_when_tl_memory_empty(self, client, tmp_path):
        project, tl = self._project_with_tl(client, tmp_path, "INJE")
        # memory.md exists but is empty / whitespace-only -> no injection.
        _memory_path(tmp_path, "INJE", tl["name"]).write_text("   \n")

        r = client.post("/api/hooks/session-start", json={
            "session_id": str(uuid.uuid4()),
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
        })
        assert r.status_code == 200, r.text
        assert "hookSpecificOutput" not in r.json()

    def test_no_injection_when_no_tl(self, client, tmp_path):
        # Project with a worker but no team-lead -> nothing to inject, no error.
        project = client.post("/api/projects", json={
            "prefix": "NOTL", "name": "No TL", "repo_path": str(tmp_path),
        }).json()
        worker = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Worky",
            "role": "backend-worker", "api_key": "notl-w",
        }).json()
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": worker["id"],
        })
        r = client.post("/api/hooks/session-start", json={
            "session_id": str(uuid.uuid4()),
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
        })
        assert r.status_code == 200, r.text
        assert "hookSpecificOutput" not in r.json()
