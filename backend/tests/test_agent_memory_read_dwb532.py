# Path: tests/test_agent_memory_read_dwb532.py
# File: test_agent_memory_read_dwb532.py
# Created: 2026-09-15
# Purpose: DWB-532: GET /api/agents/{id}/memory returns memory.md content plus the SERVER token estimate, ceiling, and headroom from the shared estimator; 404 names the agent when memory.md is missing.
# Caller: pytest
# Callees: GET /api/agents/{agent_id}/memory, POST /api/agents/{agent_id}/memory/append, app.config.token_budget
# Data In: tmp_path repo, factory project + agent
# Data Out: Assertions on response shape, estimator agreement, error mapping
# Last Modified: 2026-09-15 (DWB-532)

"""DWB-532: the memory API gains a read so condensing is not trial and error."""

from pathlib import Path

from app.config.token_budget import TOKEN_CEILINGS, estimate_tokens


def _mem_path(repo_path, prefix, name):
    return Path(repo_path) / ".dwb/memory" / prefix / name / "memory.md"


def _project_and_agent(client, tmp_path, prefix, name="Reader", repo_path=True):
    body = {"prefix": prefix, "name": f"Project {prefix}"}
    if repo_path:
        body["repo_path"] = str(tmp_path)
    project = client.post("/api/projects", json=body).json()
    agent = client.post("/api/agents", json={
        "project_id": project["id"], "name": name,
        "role": "backend-worker", "api_key": f"mr-{prefix}",
    }).json()
    return project, agent


class TestReadMemory:
    def test_exact_shape_and_estimator_agreement(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "MR1")
        path = _mem_path(tmp_path, "MR1", "Reader")
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "## 2026-09-01T00:00:00+00:00\nlesson one: always curl the live server\n"
        path.write_text(text, encoding="utf-8")

        r = client.get(f"/api/agents/{agent['id']}/memory")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) == {"content", "est_tokens", "ceiling", "headroom"}
        assert body["content"] == text
        assert body["est_tokens"] == estimate_tokens(text)
        assert body["ceiling"] == TOKEN_CEILINGS["memory_main"]
        assert body["headroom"] == body["ceiling"] - body["est_tokens"]

    def test_empty_scaffolded_file_reads_zero(self, client, tmp_path):
        """Scaffold creates an empty memory.md on agent create; reading it is a
        200 with zero tokens and full headroom, not a 404."""
        _, agent = _project_and_agent(client, tmp_path, "MR2")
        assert _mem_path(tmp_path, "MR2", "Reader").exists()
        r = client.get(f"/api/agents/{agent['id']}/memory")
        assert r.status_code == 200, r.text
        assert r.json()["est_tokens"] == 0
        assert r.json()["headroom"] == TOKEN_CEILINGS["memory_main"]

    def test_round_trip_after_append(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "MR3")
        note = "Trying X, hit Y, working around with Z."
        a = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": note,
        })
        assert a.status_code == 201, a.text
        r = client.get(f"/api/agents/{agent['id']}/memory")
        assert r.status_code == 200
        body = r.json()
        assert note in body["content"]
        assert body["est_tokens"] == estimate_tokens(body["content"])
        assert body["est_tokens"] > 0

    def test_headroom_negative_when_over_ceiling(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "MR4")
        path = _mem_path(tmp_path, "MR4", "Reader")
        path.parent.mkdir(parents=True, exist_ok=True)
        over = "word " * (TOKEN_CEILINGS["memory_main"] + 500)
        path.write_text(over, encoding="utf-8")
        r = client.get(f"/api/agents/{agent['id']}/memory")
        assert r.status_code == 200
        assert r.json()["headroom"] < 0
        assert r.json()["est_tokens"] == estimate_tokens(over)

    def test_estimate_matches_what_append_gates_on(self, client, tmp_path):
        """One-shot condense sizing: the read's headroom predicts whether an
        append of N tokens will be accepted."""
        _, agent = _project_and_agent(client, tmp_path, "MR5")
        ceiling = TOKEN_CEILINGS["memory_main"]
        path = _mem_path(tmp_path, "MR5", "Reader")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x " * (ceiling - 30), encoding="utf-8")
        headroom = client.get(f"/api/agents/{agent['id']}/memory").json()["headroom"]
        assert 0 < headroom < 60
        big = "y " * (headroom + 50)
        r = client.post(f"/api/agents/{agent['id']}/memory/append", json={
            "file": "memory", "content": big,
        })
        assert r.status_code == 400
        assert "ceiling" in r.json()["detail"]


class TestReadMemoryErrors:
    def test_missing_file_404_names_agent(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "MR6", name="Ghost")
        _mem_path(tmp_path, "MR6", "Ghost").unlink()
        r = client.get(f"/api/agents/{agent['id']}/memory")
        assert r.status_code == 404, r.text
        detail = r.json()["detail"]
        assert "Ghost" in detail
        assert str(agent["id"]) in detail
        assert "memory.md" in detail

    def test_unknown_agent_404(self, client):
        r = client.get("/api/agents/999999/memory")
        assert r.status_code == 404
        assert "999999" in r.json()["detail"]

    def test_project_without_repo_path_400(self, client, tmp_path):
        _, agent = _project_and_agent(client, tmp_path, "MR7", repo_path=False)
        r = client.get(f"/api/agents/{agent['id']}/memory")
        assert r.status_code == 400
        assert "repo_path" in r.json()["detail"]
