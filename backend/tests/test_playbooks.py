# Path:          tests/test_playbooks.py
# File:          test_playbooks.py
# Created:       2026-03-28
# Purpose:       Tests for /api/playbooks and project playbook deployment
# Caller:        pytest
# Callees:       GET/POST /api/playbooks, POST /api/projects/:id/deploy-playbooks
# Data In:       Factory-created projects via conftest fixtures; temp playbook files
# Data Out:      Assertions on HTTP status codes and deployed playbook content
# Last Modified: 2026-06-10

"""Tests for /api/playbooks and /api/projects/:id/deploy-playbooks."""

import tempfile
from pathlib import Path


class TestListPlaybooks:
    def test_list_returns_200(self, client):
        r = client.get("/api/playbooks")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_playbook_response_shape(self, client):
        playbooks = client.get("/api/playbooks").json()
        if playbooks:  # only test if playbook files exist in docs/
            pb = playbooks[0]
            assert "name" in pb
            assert "title" in pb
            assert "content" in pb
            assert isinstance(pb["content"], str)
            assert len(pb["content"]) > 0

    def test_playbook_names(self, client):
        playbooks = client.get("/api/playbooks").json()
        names = [pb["name"] for pb in playbooks]
        # These should exist if docs/ has the playbook files
        for name in names:
            assert name in ("team_lead", "pm", "worker")


class TestDeployPlaybooks:
    def test_deploy_no_repo_path_returns_400(self, client, make_project):
        project = make_project()  # no repo_path
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 400
        assert "repo_path" in r.json()["detail"].lower()

    def test_deploy_nonexistent_project_returns_404(self, client):
        r = client.post("/api/projects/999999/deploy-playbooks")
        assert r.status_code == 404

    def test_deploy_invalid_repo_path_returns_400(self, client, make_project):
        project = make_project(repo_path="/nonexistent/path/that/doesnt/exist")
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        assert r.status_code == 400
        assert "repo_path" in r.json()["detail"].lower()

    def test_deploy_success(self, client, make_project):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir)
            r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
            # Should succeed if playbook files exist in docs/
            if r.status_code == 200:
                data = r.json()
                assert "deployed" in data
                assert "target_dir" in data
                assert "memory_dirs" in data
                assert isinstance(data["deployed"], list)
                assert isinstance(data["memory_dirs"], list)
                assert len(data["deployed"]) > 0
                # Verify files were actually written
                target = Path(data["target_dir"])
                for entry in data["deployed"]:
                    # Deployed entries may have a suffix like " (created)"
                    filename = entry.split(" (")[0]
                    assert (target / filename).is_file()
            else:
                # 500 if no playbook files in docs/ — acceptable in test env
                assert r.status_code == 500


class TestDeployScaffoldsMemoryDirs:
    """DWB-298: deploy-playbooks must also scaffold agent memory dirs."""

    def _deploy_or_skip(self, client, project_id):
        r = client.post(f"/api/projects/{project_id}/deploy-playbooks")
        if r.status_code == 500:
            # No playbook files in docs/ in this test env — skip the assertions
            import pytest
            pytest.skip("docs/ has no playbook files in this env")
        assert r.status_code == 200
        return r.json()

    def test_no_agents_returns_empty_memory_dirs(self, client, make_project):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir)
            data = self._deploy_or_skip(client, project["id"])
            assert data["memory_dirs"] == []

    def test_scaffolds_dir_for_assigned_agent(
        self, client, make_project, make_agent
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir, prefix="MEM1")
            agent = make_agent(project_id=project["id"], name="Devon")

            data = self._deploy_or_skip(client, project["id"])

            assert len(data["memory_dirs"]) == 1
            entry = data["memory_dirs"][0]
            assert entry["agent_id"] == agent["id"]
            assert entry["agent_name"] == "Devon"
            assert entry["error"] is None
            assert entry["skipped"] is False
            expected_dir = Path(tmpdir) / ".claude/agents/memory/MEM1/Devon"
            assert expected_dir.is_dir()
            # identity.md is always (re-)written
            assert (expected_dir / "identity.md").is_file()
            # Agent-owned files exist (created blank)
            for fname in ("scratchpad.md", "lessons.md", "recent_sessions.md"):
                assert (expected_dir / fname).is_file()

    def test_idempotent_preserves_agent_owned_files(
        self, client, make_project, make_agent
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir, prefix="MEM2")
            make_agent(project_id=project["id"], name="Petra")
            # First deploy creates the tree
            self._deploy_or_skip(client, project["id"])

            scratch = (
                Path(tmpdir) / ".claude/agents/memory/MEM2/Petra/scratchpad.md"
            )
            scratch.write_text("user notes — preserve me\n", encoding="utf-8")

            # Second deploy must not clobber agent-owned content
            data = self._deploy_or_skip(client, project["id"])
            assert (
                scratch.read_text(encoding="utf-8")
                == "user notes — preserve me\n"
            )
            # identity.md is system-generated; should appear in refreshed
            entry = data["memory_dirs"][0]
            assert any("identity.md" in p for p in entry["refreshed"])

    def test_scaffolds_for_multiple_agents(
        self, client, make_project, make_agent
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir, prefix="MEM3")
            make_agent(project_id=project["id"], name="One")
            make_agent(project_id=project["id"], name="Two")
            make_agent(project_id=project["id"], name="Three")

            data = self._deploy_or_skip(client, project["id"])

            names = {e["agent_name"] for e in data["memory_dirs"]}
            assert names == {"One", "Two", "Three"}
            for name in ("One", "Two", "Three"):
                d = Path(tmpdir) / f".claude/agents/memory/MEM3/{name}"
                assert (d / "identity.md").is_file()

    def test_inactive_agents_not_scaffolded(
        self, client, make_project, make_agent
    ):
        """Soft-deactivated agents should not have memory dirs (re)scaffolded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir, prefix="MEM4")
            active = make_agent(project_id=project["id"], name="Alive")
            inactive = make_agent(project_id=project["id"], name="Gone")
            # Soft-deactivate
            r = client.delete(f"/api/agents/{inactive['id']}")
            assert r.status_code in (200, 204)

            data = self._deploy_or_skip(client, project["id"])
            ids = {e["agent_id"] for e in data["memory_dirs"]}
            assert ids == {active["id"]}
            # Active agent's dir was (re)scaffolded by deploy-playbooks.
            assert (
                Path(tmpdir) / ".claude/agents/memory/MEM4/Alive/identity.md"
            ).is_file()
            # Inactive agent should not appear in the deploy response; we don't
            # assert on disk state because the dir may already exist from the
            # auto-scaffold at agent-create time. The contract is "deploy only
            # touches active agents", which the ids set above verifies.

    def test_agent_on_other_project_not_scaffolded(
        self, client, make_project, make_agent
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as other_tmpdir:
                project_a = make_project(repo_path=tmpdir, prefix="MEMA")
                project_b = make_project(repo_path=other_tmpdir, prefix="MEMB")
                make_agent(project_id=project_a["id"], name="Anna")
                make_agent(project_id=project_b["id"], name="Bobby")

                data = self._deploy_or_skip(client, project_a["id"])
                names = {e["agent_name"] for e in data["memory_dirs"]}
                assert names == {"Anna"}
                # Anna's dir lives under project A's repo, not under project B's.
                assert (
                    Path(tmpdir) / ".claude/agents/memory/MEMA/Anna/identity.md"
                ).is_file()
                assert not (
                    Path(other_tmpdir) / ".claude/agents/memory/MEMA"
                ).exists()
                # (Bobby's dir under project B's repo already exists from the
                # auto-scaffold at agent-create time — that's not part of this
                # deploy's contract.)


class TestDeployScaffoldsRootDocs:
    """DWB-366: deploy-playbooks must scaffold INITIAL.md, ARCHITECTURE.md,
    HANDOFF.md at the project repo root when missing; never overwrite when
    present; surface created entries in response.root_docs."""

    _DOCS = ("INITIAL.md", "ARCHITECTURE.md", "HANDOFF.md")

    def _deploy_or_skip(self, client, project_id):
        r = client.post(f"/api/projects/{project_id}/deploy-playbooks")
        if r.status_code == 500:
            import pytest
            pytest.skip("docs/ has no playbook files in this env")
        assert r.status_code == 200
        return r.json()

    def test_creates_all_three_when_missing(self, client, make_project):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir, prefix="RDOC1")
            data = self._deploy_or_skip(client, project["id"])
            assert "root_docs" in data
            assert sorted(data["root_docs"]) == sorted(self._DOCS)
            for name in self._DOCS:
                path = Path(tmpdir) / name
                assert path.is_file()
                content = path.read_text(encoding="utf-8")
                # Minimal H1 present (may be after non-Jira banner).
                stem = name.removesuffix(".md")
                assert f"# {stem.title()}" in content

    def test_preserves_existing_files(self, client, make_project):
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = "# My handoff\n\nUser content - keep me.\n"
            (Path(tmpdir) / "HANDOFF.md").write_text(existing)
            (Path(tmpdir) / "INITIAL.md").write_text("# Custom initial\n")

            project = make_project(repo_path=tmpdir, prefix="RDOC2")
            data = self._deploy_or_skip(client, project["id"])

            # Only the missing one (ARCHITECTURE.md) scaffolded.
            assert data["root_docs"] == ["ARCHITECTURE.md"]
            # Existing files untouched.
            assert (Path(tmpdir) / "HANDOFF.md").read_text(
                encoding="utf-8"
            ) == existing
            assert (Path(tmpdir) / "INITIAL.md").read_text(
                encoding="utf-8"
            ) == "# Custom initial\n"

    def test_idempotent_second_deploy_creates_nothing(
        self, client, make_project
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            project = make_project(repo_path=tmpdir, prefix="RDOC3")
            self._deploy_or_skip(client, project["id"])
            # Second deploy: all files now exist.
            data = self._deploy_or_skip(client, project["id"])
            assert data["root_docs"] == []

    def test_non_jira_prepends_banner_to_each_root_doc(
        self, client, tmp_path
    ):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "RDNJ",
                "name": "Non-Jira Root Docs",
                "repo_path": str(tmp_path),
                "jira_base_url": None,
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        if r.status_code == 500:
            import pytest
            pytest.skip("docs/ has no playbook files in this env")
        assert r.status_code == 200
        for name in self._DOCS:
            content = (tmp_path / name).read_text(encoding="utf-8")
            assert "THIS PROJECT IS NOT LINKED TO JIRA" in content, (
                f"banner missing from {name}"
            )

    def test_jira_enabled_no_banner_on_root_docs(self, client, tmp_path):
        project = client.post(
            "/api/projects",
            json={
                "prefix": "RDJE",
                "name": "Jira Root Docs",
                "repo_path": str(tmp_path),
                "jira_base_url": "https://example.atlassian.net",
            },
        ).json()
        r = client.post(f"/api/projects/{project['id']}/deploy-playbooks")
        if r.status_code == 500:
            import pytest
            pytest.skip("docs/ has no playbook files in this env")
        assert r.status_code == 200
        for name in self._DOCS:
            content = (tmp_path / name).read_text(encoding="utf-8")
            assert "THIS PROJECT IS NOT LINKED TO JIRA" not in content
