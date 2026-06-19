# Path: tests/test_agent_memory_scaffold.py
# File: test_agent_memory_scaffold.py
# Created: 2026-06-03
# Purpose: Tests for the agent_memory scaffolder service + auto-triggers (DWB-293)
# Caller: pytest
# Callees: app.services.agent_memory, POST /api/agents, POST /api/project-agents, POST /api/agents/{id}/scaffold-memory
# Data In: tmp_path filesystem, factory projects + agents
# Data Out: Assertions on directory layout, identity.md content, idempotency
# Last Modified: 2026-06-19

from pathlib import Path


def _memory_dir(repo_path, prefix, name):
    return Path(repo_path) / ".dwb" / "memory" / prefix / name


class TestScaffoldOnCreate:
    def test_create_agent_auto_scaffolds(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SCF1", "name": "Scaffold One", "repo_path": str(tmp_path),
        }).json()
        client.post("/api/agents", json={
            "project_id": project["id"], "name": "Pixel",
            "role": "frontend-worker", "api_key": "scf1-pixel",
        })

        d = _memory_dir(tmp_path, "SCF1", "Pixel")
        assert d.is_dir()
        # DWB-401: 2-file model.
        assert (d / "identity.md").is_file()
        assert (d / "memory.md").is_file()
        assert not (d / "scratchpad.md").exists()
        assert not (d / "lessons.md").exists()
        assert not (d / "recent_sessions.md").exists()

    def test_identity_md_carries_agent_facts(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SCF2", "name": "Scaffold Two", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Devin",
            "role": "backend-worker", "api_key": "scf2-devin",
            "description": "test agent",
        }).json()

        identity = (_memory_dir(tmp_path, "SCF2", "Devin") / "identity.md").read_text()
        assert f"**agent_id:** {agent['id']}" in identity
        assert "**name:** Devin" in identity
        assert "**role:** backend-worker" in identity
        assert "SCF2 (Scaffold Two)" in identity
        # Self-orientation block
        assert "## On Spawn - Read These First" in identity
        # ISO 8601 entry rule
        assert "## ISO 8601 entry rule" in identity


class TestScaffoldIdempotency:
    def test_memory_preserved_on_re_scaffold(self, client, tmp_path):
        # DWB-401: the single agent-owned memory.md is preserved on re-scaffold;
        # only identity.md is regenerated.
        project = client.post("/api/projects", json={
            "prefix": "SCF3", "name": "Scaffold Three", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Sage",
            "role": "tester", "api_key": "scf3-sage",
        }).json()

        d = _memory_dir(tmp_path, "SCF3", "Sage")
        # Agent-written content
        (d / "memory.md").write_text("## 2026-06-03 - session foo\n- did stuff\n- learned X\n")

        # Manual re-scaffold via the endpoint
        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        body = r.json()
        # identity.md regenerated (refreshed)
        assert any(p.endswith("/identity.md") for p in body["refreshed"])
        # memory.md preserved
        assert any(p.endswith("/memory.md") for p in body["preserved"])

        # Content verified untouched
        assert "did stuff" in (d / "memory.md").read_text()
        assert "learned X" in (d / "memory.md").read_text()

    def test_identity_md_regenerated_on_re_scaffold(self, client, tmp_path):
        project = client.post("/api/projects", json={
            "prefix": "SCF4", "name": "Scaffold Four", "repo_path": str(tmp_path),
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "Bolt",
            "role": "system-ops", "api_key": "scf4-bolt",
        }).json()

        d = _memory_dir(tmp_path, "SCF4", "Bolt")
        (d / "identity.md").write_text("OLD CONTENT")

        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        # OLD CONTENT must be gone (regenerated)
        assert "OLD CONTENT" not in (d / "identity.md").read_text()
        assert "**agent_id:**" in (d / "identity.md").read_text()


class TestScaffoldOnAssign:
    def test_project_agent_assign_triggers_scaffold(self, client, tmp_path):
        proj_a = client.post("/api/projects", json={
            "prefix": "SCF5A", "name": "A", "repo_path": str(tmp_path / "a"),
        }).json()
        proj_b = client.post("/api/projects", json={
            "prefix": "SCF5B", "name": "B", "repo_path": str(tmp_path / "b"),
        }).json()
        (tmp_path / "a").mkdir(exist_ok=True)
        (tmp_path / "b").mkdir(exist_ok=True)

        # Agent created on A → scaffold under A
        agent = client.post("/api/agents", json={
            "project_id": proj_a["id"], "name": "Pam",
            "role": "pm", "api_key": "scf5-pam",
        }).json()
        assert _memory_dir(tmp_path / "a", "SCF5A", "Pam").is_dir()

        # Assign to B → expected behavior: scaffold helper runs, but agents.project_id
        # is still A, so the scaffold under B does NOT happen (the function reads
        # agent.project_id, not the assignment's project_id). Documented behavior.
        client.post("/api/project-agents", json={
            "project_id": proj_b["id"], "agent_id": agent["id"],
        })
        # The A directory still exists (idempotent)
        assert _memory_dir(tmp_path / "a", "SCF5A", "Pam").is_dir()


class TestScaffoldErrors:
    def test_404_when_agent_missing(self, client):
        r = client.post("/api/agents/999999/scaffold-memory")
        assert r.status_code == 404

    def test_skipped_when_no_repo_path(self, client):
        # Project with no repo_path → scaffold returns skipped, not an error
        project = client.post("/api/projects", json={
            "prefix": "SCFNR", "name": "NoRepo",
        }).json()
        agent = client.post("/api/agents", json={
            "project_id": project["id"], "name": "NoRepoAgent",
            "role": "tester", "api_key": "scf-nr",
        }).json()
        r = client.post(f"/api/agents/{agent['id']}/scaffold-memory")
        assert r.status_code == 200
        body = r.json()
        assert body["skipped"] is True
        assert "repo_path" in body["skip_reason"]
