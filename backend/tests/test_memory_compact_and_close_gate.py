# Path: tests/test_memory_compact_and_close_gate.py
# File: test_memory_compact_and_close_gate.py
# Created: 2026-06-17
# Purpose: Tests for POST /api/agents/{id}/memory/compact (replace + ceiling enforce) and the session-close compaction gate.
# Caller: pytest
# Callees: /api/agents/{id}/memory/compact, /api/sessions/open, /api/sessions/{id}/close
# Data In: tmp_path filesystem, factory project + agent
# Data Out: assertions on overwrite semantics, ceiling refusal, and the hard close gate
# Last Modified: 2026-06-17

"""Memory compaction = full-file REPLACE with a hard ceiling, plus the
session-close gate that refuses to close until the project's spawn-loaded
docs are within budget.

memory_scratchpad ceiling = 2000 tokens; estimate_tokens = max(len//4, words),
so >8000 chars is reliably over, a short string is reliably under.
"""

from pathlib import Path

OVER = "data " * 2000  # 10,000 chars -> ~2500 tokens, over the 2000 ceiling
UNDER = "compacted: shipped the gate, fixed the estimator"


def _mem_dir(repo_path, prefix, name):
    return Path(repo_path) / ".claude/agents/memory" / prefix / name


def _project_and_agent(client, tmp_path, prefix, name="Memo"):
    project = client.post("/api/projects", json={
        "prefix": prefix, "name": f"Project {prefix}", "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": name,
        "role": "backend-worker", "api_key": f"mem-{prefix}",
    }).json()
    return project, agent


class TestCompactEndpoint:
    def test_over_ceiling_is_refused_422(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CMP1")
        r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "scratchpad", "content": OVER,
        })
        assert r.status_code == 422, r.text
        assert "ceiling" in r.json()["detail"].lower()

    def test_within_ceiling_overwrites_not_appends(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CMP2")
        path = _mem_dir(tmp_path, "CMP2", "Memo") / "scratchpad.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("OLD BLOATED CONTENT\n" * 50, encoding="utf-8")

        r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "scratchpad", "content": UNDER,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tokens"] <= body["ceiling"]
        # Replace, not append: old content is gone.
        on_disk = path.read_text(encoding="utf-8")
        assert "OLD BLOATED" not in on_disk
        assert on_disk.strip() == UNDER

    def test_empty_content_refused_400(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CMP3")
        r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "scratchpad", "content": "   ",
        })
        assert r.status_code == 400, r.text

    def test_identity_not_compactable_422_schema(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CMP4")
        r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "identity", "content": "x",
        })
        assert r.status_code == 422, r.text  # not in the Literal enum


class TestCloseCompactionGate:
    def _seed_over_ceiling(self, tmp_path, prefix, name):
        mem = _mem_dir(tmp_path, prefix, name)
        mem.mkdir(parents=True, exist_ok=True)
        # keep only an over-ceiling scratchpad; drop any scaffolded siblings
        for f in ("identity.md", "lessons.md", "recent_sessions.md"):
            (mem / f).unlink(missing_ok=True)
        (mem / "scratchpad.md").write_text(OVER, encoding="utf-8")

    def test_ai_close_blocked_until_compacted(self, client, tmp_path):
        project, agent = _project_and_agent(client, tmp_path, "GATE", name="Gus")
        self._seed_over_ceiling(tmp_path, "GATE", "Gus")

        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"], "open_method": "ai_confident",
        }).json()
        sid = opened["id"]

        # Close attempt: past the headline gate (headline supplied), into the
        # compaction gate -> 422.
        r = client.post(f"/api/sessions/{sid}/close", json={
            "close_method": "ai_confident", "close_reason": "explicit",
            "headline": "built compaction gate this session",
        })
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert "Compaction gate" in detail
        assert "scratchpad" in detail

        # Compact the offending file under ceiling.
        rc = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "scratchpad", "content": UNDER,
        })
        assert rc.status_code == 200, rc.text

        # Retry close -> now succeeds.
        r2 = client.post(f"/api/sessions/{sid}/close", json={
            "close_method": "ai_confident", "close_reason": "explicit",
            "headline": "built compaction gate this session",
        })
        assert r2.status_code == 200, r2.text
        assert r2.json()["closed_at"] is not None

    def test_idle_close_exempt_from_compaction_gate(self, client, tmp_path):
        project, _ = _project_and_agent(client, tmp_path, "GATE2", name="Ivy")
        self._seed_over_ceiling(tmp_path, "GATE2", "Ivy")
        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"], "open_method": "ai_confident",
        }).json()
        # idle sweeper-style close: exempt even with an over-ceiling file present
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "idle_timeout", "close_reason": "idle",
        })
        assert r.status_code == 200, r.text
