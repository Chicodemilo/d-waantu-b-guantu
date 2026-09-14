# Path: tests/test_memory_compact_and_close_gate.py
# File: test_memory_compact_and_close_gate.py
# Created: 2026-06-17
# Purpose: Tests for POST /api/agents/{id}/memory/compact (replace, hard ceiling) and that memory NEVER blocks a session close (DWB-401). DWB-518: the ceiling is a hard refusal, not a passive trim.
# Caller: pytest
# Callees: /api/agents/{id}/memory/compact, /api/agents/{id}/memory/append, /api/sessions/open, /api/sessions/{id}/close
# Data In: tmp_path filesystem, factory project + agent
# Data Out: assertions on replace semantics, over-ceiling refusal, and that memory is gate-exempt at close
# Last Modified: 2026-09-14 (DWB-518: over-ceiling append/compact refuse; no passive trim)

"""Memory compaction + the session-close compaction gate.

DWB-401: the memory model is 2 files (identity.md + the single free-form
memory.md), memory.md ceiling = 4500 tokens.

DWB-518 (Miles ruling: no silent eviction): the ceiling is a HARD gate on the
WRITE path, not a passive trim - an over-ceiling append/compact is REFUSED 400
and nothing is dropped; the agent condenses first. Note this is orthogonal to
the session-CLOSE gate: memory is still gate-EXEMPT at close (an over-ceiling
memory.md on disk never blocks a close), which the TestCloseNotBlockedByMemory
class below still pins.

estimate_tokens = max(len//4, words). memory.md ceiling = 4500 tokens, so a
~20000-char blob (~5000 tokens) is reliably over; a short string is under.
"""

from pathlib import Path

# ~5000 tokens (20000 chars) - over the 4500 memory.md ceiling.
OVER = "data " * 4000
UNDER = "compacted: shipped the gate, fixed the estimator"


def _mem_dir(repo_path, prefix, name):
    return Path(repo_path) / ".dwb/memory" / prefix / name


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
    def test_over_ceiling_refused_400_not_trimmed(self, client, tmp_path):
        # DWB-518: no silent trim. A multi-block over-ceiling submit is REFUSED
        # 400 (nothing written), not accepted-and-trimmed.
        _, agent = _project_and_agent(client, tmp_path, "CMP1")
        blocks = "".join(
            f"## 2026-06-1{i}T00:00:00+00:00\n{'data ' * 600}\n" for i in range(6)
        )
        path = _mem_dir(tmp_path, "CMP1", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## seed\nkeep this\n", encoding="utf-8")
        r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "memory", "content": blocks,
        })
        assert r.status_code == 400, r.text
        assert "ceiling" in r.json()["detail"].lower()
        # Nothing written: the prior file is untouched.
        assert path.read_text(encoding="utf-8") == "## seed\nkeep this\n"

    def test_within_ceiling_overwrites_not_appends(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CMP2")
        path = _mem_dir(tmp_path, "CMP2", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("OLD BLOATED CONTENT\n" * 50, encoding="utf-8")

        r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "memory", "content": UNDER,
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
            "file": "memory", "content": "   ",
        })
        assert r.status_code == 400, r.text

    def test_identity_not_compactable_422_schema(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CMP4")
        r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
            "file": "identity", "content": "x",
        })
        assert r.status_code == 422, r.text  # not in the Literal enum

    def test_retired_file_names_rejected(self, client, tmp_path):
        # DWB-401: scratchpad/lessons/recent_sessions are no longer valid files.
        _, agent = _project_and_agent(client, tmp_path, "CMP5")
        for retired in ("scratchpad", "lessons", "recent_sessions"):
            r = client.post(f"/api/agents/{agent['id']}/memory/compact", json={
                "file": retired, "content": "x",
            })
            assert r.status_code == 422, f"{retired}: {r.text}"


class TestAppendCeilingRefusal:
    """DWB-518: memory.md's ceiling is a HARD gate. An append that would push it
    over the ceiling is REFUSED 400 - nothing is dropped, no entry evicted. The
    agent must condense first, then retry."""

    def test_append_past_ceiling_refused_and_nothing_dropped(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "TRIM1")
        path = _mem_dir(tmp_path, "TRIM1", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        # Seed several large OLD blocks well over the 4500 ceiling
        # (~1200 tokens each x 5 = ~6000).
        seed = "".join(
            f"## 2026-06-0{i}T00:00:00+00:00\nOLDBLOCK{i} {'x ' * 1200}\n"
            for i in range(1, 6)
        )
        path.write_text(seed, encoding="utf-8")

        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": "NEWEST distinctive marker line",
        })
        # Refused, actionable body naming the ceiling + condense instruction.
        assert r.status_code == 400, r.text
        detail = r.json()["detail"].lower()
        assert "ceiling" in detail
        assert "condense" in detail

        # No silent drop: the file is byte-for-byte unchanged, oldest block kept.
        text = path.read_text(encoding="utf-8")
        assert text == seed
        assert "OLDBLOCK1" in text
        assert "NEWEST distinctive marker line" not in text

    def test_small_append_not_refused(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "TRIM2")
        path = _mem_dir(tmp_path, "TRIM2", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## 2026-06-01T00:00:00+00:00\nkeep me\n", encoding="utf-8")
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": "second small note",
        })
        assert r.status_code == 201, r.text
        text = path.read_text(encoding="utf-8")
        assert "keep me" in text
        assert "second small note" in text


class TestCloseNotBlockedByMemory:
    """DWB-401 litmus: memory is gate-exempt. An over-ceiling memory.md must
    NOT block an ai_confident session close."""

    def _seed_over_ceiling_memory(self, tmp_path, prefix, name):
        mem = _mem_dir(tmp_path, prefix, name)
        mem.mkdir(parents=True, exist_ok=True)
        (mem / "memory.md").write_text(OVER, encoding="utf-8")

    def test_over_ceiling_memory_does_not_block_close(self, client, tmp_path):
        # DWB-401: previously an over-ceiling memory file blocked the close.
        # Memory is now gate-exempt, so the close SUCCEEDS.
        project, agent = _project_and_agent(client, tmp_path, "GATE", name="Gus")
        self._seed_over_ceiling_memory(tmp_path, "GATE", "Gus")

        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"], "open_method": "ai_confident",
        }).json()
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "ai_confident", "close_reason": "explicit",
            "headline": "memory no longer blocks the close",
        })
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None

    def test_over_ceiling_memory_does_not_block_alongside_playbook(
        self, client, tmp_path
    ):
        # DWB-401: over-ceiling memory.md + over-ceiling (exempt) playbook ->
        # close STILL succeeds. Neither blocks.
        project, _ = _project_and_agent(client, tmp_path, "GATE4", name="Quinn")
        self._seed_over_ceiling_memory(tmp_path, "GATE4", "Quinn")
        claude = Path(tmp_path) / ".claude"
        claude.mkdir(parents=True, exist_ok=True)
        (claude / "worker_playbook.md").write_text(OVER, encoding="utf-8")
        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"], "open_method": "ai_confident",
        }).json()
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "ai_confident", "close_reason": "explicit",
            "headline": "memory and playbook both exempt",
        })
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None

    def test_idle_close_succeeds_with_over_ceiling_memory(self, client, tmp_path):
        project, _ = _project_and_agent(client, tmp_path, "GATE2", name="Ivy")
        self._seed_over_ceiling_memory(tmp_path, "GATE2", "Ivy")
        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"], "open_method": "ai_confident",
        }).json()
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "idle_timeout", "close_reason": "idle",
        })
        assert r.status_code == 200, r.text


class TestCompactionGateRespectsConsolidationToggle:
    """DWB-400 (reconciled for DWB-401): the session-close compaction gate is
    opt-in via force_consolidation. Memory no longer feeds it (DWB-401, gate-
    exempt), but TL-owned ROOT docs still do. So with force_consolidation OFF
    the gate is skipped entirely; with it ON an over-ceiling root doc blocks the
    ai_confident close. (Replaces the old memory-seeded OFF-skip test, whose
    premise - memory feeding the gate - is gone under DWB-401.)
    """

    def _project(self, client, tmp_path, prefix, *, force_consolidation):
        # Over-ceiling HANDOFF.md = a TL-owned root doc that DOES still gate.
        # It exists, so the sprint-level doc-existence gate is irrelevant; a
        # session close only runs the headline + compaction gates.
        (Path(tmp_path) / "HANDOFF.md").write_text(OVER, encoding="utf-8")
        return client.post("/api/projects", json={
            "prefix": prefix, "name": f"Project {prefix}",
            "repo_path": str(tmp_path),
            "force_consolidation": force_consolidation,
        }).json()

    def test_off_skips_gate_even_with_over_ceiling_root_doc(self, client, tmp_path):
        project = self._project(client, tmp_path, "CTOG1", force_consolidation=False)
        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"], "open_method": "ai_confident",
        }).json()
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "ai_confident", "close_reason": "explicit",
            "headline": "consolidation off so compaction gate skipped",
        })
        assert r.status_code == 200, r.text
        assert r.json()["closed_at"] is not None

    def test_on_blocks_close_on_over_ceiling_root_doc(self, client, tmp_path):
        project = self._project(client, tmp_path, "CTOG2", force_consolidation=True)
        opened = client.post("/api/sessions/open", json={
            "project_id": project["id"], "open_method": "ai_confident",
        }).json()
        r = client.post(f"/api/sessions/{opened['id']}/close", json={
            "close_method": "ai_confident", "close_reason": "explicit",
            "headline": "consolidation on so root doc gates",
        })
        assert r.status_code == 422, r.text
        assert "Compaction gate" in r.json()["detail"]
        assert "HANDOFF" in r.json()["detail"]
