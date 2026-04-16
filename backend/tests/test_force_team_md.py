# Path:          tests/test_force_team_md.py
# File:          test_force_team_md.py
# Created:       2026-04-16
# Purpose:       Tests for force_team_md gate — default value, gate-status pass/fail, toggle
# Caller:        pytest
# Callees:       FastAPI TestClient → project routers (gate-status, PATCH)
# Data In:       Factory fixtures, tmp_path for repo_path simulation
# Data Out:      Assertions on gate status and project field values
# Last Modified: 2026-04-16

"""Tests for the force_team_md sprint gate (DWB-244).

The force_team_md gate defaults to True (unlike other gates). When enabled,
gate-status checks for TEAM.md at the project's repo_path. Sprint closure
is blocked if the file is missing.
"""

import os


class TestForceTeamMdDefault:
    """New projects should default to force_team_md=True."""

    def test_create_project_defaults_force_team_md_true(self, client):
        r = client.post("/api/projects", json={
            "prefix": "TMD",
            "name": "Team MD Default",
        })
        assert r.status_code == 201
        assert r.json()["force_team_md"] is True

    def test_create_project_can_override_to_false(self, client):
        r = client.post("/api/projects", json={
            "prefix": "TMF",
            "name": "Team MD False",
            "force_team_md": False,
        })
        assert r.status_code == 201
        assert r.json()["force_team_md"] is False

    def test_get_project_includes_force_team_md(self, client, make_project):
        project = make_project()
        data = client.get(f"/api/projects/{project['id']}").json()
        assert "force_team_md" in data


class TestForceTeamMdToggle:
    """PATCH /api/projects/:id can toggle force_team_md on and off."""

    def test_toggle_force_team_md_off(self, client):
        project = client.post("/api/projects", json={
            "prefix": "TG1",
            "name": "Toggle Off",
        }).json()
        assert project["force_team_md"] is True

        r = client.patch(f"/api/projects/{project['id']}", json={
            "force_team_md": False,
        })
        assert r.status_code == 200
        assert r.json()["force_team_md"] is False

    def test_toggle_force_team_md_back_on(self, client):
        project = client.post("/api/projects", json={
            "prefix": "TG2",
            "name": "Toggle On",
            "force_team_md": False,
        }).json()
        assert project["force_team_md"] is False

        r = client.patch(f"/api/projects/{project['id']}", json={
            "force_team_md": True,
        })
        assert r.status_code == 200
        assert r.json()["force_team_md"] is True


class TestForceTeamMdGateStatus:
    """GET /api/projects/:id/gate-status reflects TEAM.md presence."""

    def test_gate_disabled_shows_passing(self, client):
        """force_team_md=False → gate always passes regardless of file."""
        project = client.post("/api/projects", json={
            "prefix": "GD1",
            "name": "Gate Disabled",
            "force_team_md": False,
        }).json()

        r = client.get(f"/api/projects/{project['id']}/gate-status")
        assert r.status_code == 200
        gates = {g["toggle"]: g for g in r.json()["gates"]}
        team_gate = gates["force_team_md"]
        assert team_gate["enabled"] is False
        assert team_gate["passing"] is True

    def test_gate_enabled_no_repo_path_shows_failing(self, client):
        """force_team_md=True but no repo_path → exists is None, gate fails.

        Without a repo_path the file check is skipped (exists=None), but the
        passing logic (not enabled or exists is True) evaluates to False.
        """
        project = client.post("/api/projects", json={
            "prefix": "GNR",
            "name": "Gate No Repo",
        }).json()

        r = client.get(f"/api/projects/{project['id']}/gate-status")
        assert r.status_code == 200
        gates = {g["toggle"]: g for g in r.json()["gates"]}
        team_gate = gates["force_team_md"]
        assert team_gate["enabled"] is True
        assert team_gate["exists"] is None
        assert team_gate["passing"] is False

    def test_gate_enabled_team_md_missing_shows_failing(self, client, tmp_path):
        """force_team_md=True + repo_path set but no TEAM.md → gate fails."""
        project = client.post("/api/projects", json={
            "prefix": "GMF",
            "name": "Gate Missing File",
            "repo_path": str(tmp_path),
        }).json()

        r = client.get(f"/api/projects/{project['id']}/gate-status")
        assert r.status_code == 200
        data = r.json()
        gates = {g["toggle"]: g for g in data["gates"]}
        team_gate = gates["force_team_md"]
        assert team_gate["enabled"] is True
        assert team_gate["exists"] is False
        assert team_gate["passing"] is False
        assert data["all_passing"] is False

    def test_gate_enabled_team_md_present_shows_passing(self, client, tmp_path):
        """force_team_md=True + TEAM.md exists → gate passes."""
        # Create TEAM.md in the tmp repo path
        (tmp_path / "TEAM.md").write_text("# Team\n")

        project = client.post("/api/projects", json={
            "prefix": "GMP",
            "name": "Gate Has File",
            "repo_path": str(tmp_path),
        }).json()

        r = client.get(f"/api/projects/{project['id']}/gate-status")
        assert r.status_code == 200
        data = r.json()
        gates = {g["toggle"]: g for g in data["gates"]}
        team_gate = gates["force_team_md"]
        assert team_gate["enabled"] is True
        assert team_gate["exists"] is True
        assert team_gate["passing"] is True

    def test_gate_status_includes_correct_path(self, client, tmp_path):
        """Gate status returns the expected file path."""
        project = client.post("/api/projects", json={
            "prefix": "GPT",
            "name": "Gate Path Test",
            "repo_path": str(tmp_path),
        }).json()

        r = client.get(f"/api/projects/{project['id']}/gate-status")
        gates = {g["toggle"]: g for g in r.json()["gates"]}
        team_gate = gates["force_team_md"]
        assert team_gate["path"] == os.path.join(str(tmp_path), "TEAM.md")
        assert team_gate["file"] == "TEAM.md"


class TestForceTeamMdSprintClose:
    """Sprint closure is blocked when force_team_md gate fails."""

    def _make_gated_sprint(self, client, make_epic, tmp_path):
        """Create a project with force_team_md=True, a repo_path, and an active sprint."""
        project = client.post("/api/projects", json={
            "prefix": "TSC",
            "name": "Team MD Sprint Close",
            "repo_path": str(tmp_path),
            # force_team_md defaults True, disable others to isolate
            "force_initial_md": False,
            "force_architecture_md": False,
            "force_handoff_md": False,
            "force_test_run": False,
            "force_test_coverage": False,
        }).json()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        return project, sprint

    def test_sprint_close_blocked_without_team_md(self, client, make_epic, tmp_path):
        project, sprint = self._make_gated_sprint(client, make_epic, tmp_path)

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 400
        assert "team.md" in r.json()["detail"].lower()

    def test_sprint_close_succeeds_with_team_md(self, client, make_epic, tmp_path):
        (tmp_path / "TEAM.md").write_text("# Team\n")
        project, sprint = self._make_gated_sprint(client, make_epic, tmp_path)

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_sprint_close_succeeds_when_gate_disabled(self, client, make_epic, tmp_path):
        """force_team_md=False allows close even without the file."""
        project = client.post("/api/projects", json={
            "prefix": "TSD",
            "name": "Team MD Disabled",
            "repo_path": str(tmp_path),
            "force_team_md": False,
            "force_initial_md": False,
            "force_architecture_md": False,
            "force_handoff_md": False,
            "force_test_run": False,
            "force_test_coverage": False,
        }).json()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
