# Path: tests/test_memory_write_ceiling_dwb518.py
# File: test_memory_write_ceiling_dwb518.py
# Created: 2026-09-14 (DWB-518)
# Purpose: DWB-518 - kill the silent trim. Over-ceiling memory writes
#          (append + session-complete) are REFUSED 400 with an actionable
#          condense-first body; nothing is dropped. New condense endpoint
#          full-replaces memory.md under a hard ceiling with a server-stamped
#          ISO condensed-at heading, and unblocks a refused append.
# Caller: pytest
# Callees: POST /api/agents/{id}/memory/append, /session-complete, /memory/condense
# Data In: tmp_path filesystem, factory project + agent
# Data Out: assertions on 400 refusals, no-drop invariant, condense replace + heading
# Last Modified: 2026-09-14 (DWB-518)

from pathlib import Path

# ~5000 tokens (20000 chars) - over the 4500 memory.md ceiling.
OVER = "data " * 4000
UNDER = "condensed: kept the load-bearing facts, dropped the noise"


def _mem_dir(repo_path, prefix, name):
    return Path(repo_path) / ".dwb/memory" / prefix / name


def _project_and_agent(client, tmp_path, prefix, name="Memo"):
    project = client.post("/api/projects", json={
        "prefix": prefix, "name": f"Project {prefix}", "repo_path": str(tmp_path),
    }).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": name,
        "role": "backend-worker", "api_key": f"mw-{prefix}",
    }).json()
    return project, agent


class TestAppendCeiling:
    def test_under_ceiling_append_unchanged(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "AC1")
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": "a small durable note",
        })
        assert r.status_code == 201, r.text

    def test_over_ceiling_append_refused_400(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "AC2")
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": OVER,
        })
        assert r.status_code == 400, r.text
        detail = r.json()["detail"].lower()
        assert "ceiling" in detail
        assert "condense" in detail  # actionable: condense, don't wait

    def test_over_ceiling_append_drops_nothing(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "AC3")
        path = _mem_dir(tmp_path, "AC3", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        seed = "## 2026-09-01T00:00:00+00:00\nvaluable prior entry\n"
        path.write_text(seed, encoding="utf-8")
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": OVER,
        })
        assert r.status_code == 400, r.text
        # File byte-for-byte unchanged: no eviction, no partial write.
        assert path.read_text(encoding="utf-8") == seed


class TestSessionCompleteCeiling:
    def test_under_ceiling_session_complete_unchanged(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "SC1")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-1", "summary": "shipped the ticket",
        })
        assert r.status_code == 200, r.text

    def test_over_ceiling_session_complete_refused_400(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "SC2")
        path = _mem_dir(tmp_path, "SC2", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(OVER, encoding="utf-8")
        r = client.post(f"/api/agents/{agent['id']}/session-complete", json={
            "session_id": "sess-2", "summary": "wrap-up over the ceiling",
        })
        assert r.status_code == 400, r.text
        detail = r.json()["detail"].lower()
        assert "ceiling" in detail and "condense" in detail
        # Nothing appended: the file is unchanged.
        assert path.read_text(encoding="utf-8") == OVER


class TestCondenseEndpoint:
    def test_condense_replaces_and_stamps_heading(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CD1")
        path = _mem_dir(tmp_path, "CD1", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("OLD BLOATED CONTENT\n" * 50, encoding="utf-8")

        r = client.post(f"/api/agents/{agent['id']}/memory/condense", json={
            "file": "memory", "content": UNDER,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tokens"] <= body["ceiling"]
        assert body["condensed_at"]  # ISO timestamp echoed

        on_disk = path.read_text(encoding="utf-8")
        assert "OLD BLOATED" not in on_disk          # replaced, not appended
        assert on_disk.startswith("## ")             # heading stamped
        assert "- condensed" in on_disk.splitlines()[0]
        assert UNDER in on_disk

    def test_condense_still_over_ceiling_refused_400(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CD2")
        r = client.post(f"/api/agents/{agent['id']}/memory/condense", json={
            "file": "memory", "content": OVER,
        })
        assert r.status_code == 400, r.text
        assert "ceiling" in r.json()["detail"].lower()

    def test_condense_empty_refused_400(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CD3")
        r = client.post(f"/api/agents/{agent['id']}/memory/condense", json={
            "file": "memory", "content": "   ",
        })
        assert r.status_code == 400, r.text

    def test_condense_identity_refused_422_schema(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CD4")
        r = client.post(f"/api/agents/{agent['id']}/memory/condense", json={
            "file": "identity", "content": "x",
        })
        assert r.status_code == 422, r.text  # not in the Literal enum

    def test_condense_unblocks_a_refused_append(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "CD5")
        path = _mem_dir(tmp_path, "CD5", "Memo") / "memory.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(OVER, encoding="utf-8")  # already over ceiling

        # Append is refused while over ceiling.
        blocked = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": "new note",
        })
        assert blocked.status_code == 400, blocked.text

        # Condense down to a lean file...
        condensed = client.post(f"/api/agents/{agent['id']}/memory/condense", json={
            "file": "memory", "content": UNDER,
        })
        assert condensed.status_code == 200, condensed.text

        # ...and the same append now lands.
        ok = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": "new note",
        })
        assert ok.status_code == 201, ok.text
        assert "new note" in path.read_text(encoding="utf-8")
