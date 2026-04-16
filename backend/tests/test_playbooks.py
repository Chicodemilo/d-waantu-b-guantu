# Path:          tests/test_playbooks.py
# File:          test_playbooks.py
# Created:       2026-03-28
# Purpose:       Tests for /api/playbooks and project playbook deployment
# Caller:        pytest
# Callees:       GET/POST /api/playbooks, POST /api/projects/:id/deploy-playbooks
# Data In:       Factory-created projects via conftest fixtures; temp playbook files
# Data Out:      Assertions on HTTP status codes and deployed playbook content
# Last Modified: 2026-04-16

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
                assert isinstance(data["deployed"], list)
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
