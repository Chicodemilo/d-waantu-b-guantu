# Path:          tests/test_completion_gates.py
# File:          test_completion_gates.py
# Created:       2026-03-28
# Purpose:       Tests for sprint completion validation gates (force_test_run, force_test_coverage)
# Caller:        pytest
# Callees:       POST/PATCH /api/projects, POST/PATCH /api/sprints, POST /api/test-results
# Data In:       Factory-created projects, epics, test results via conftest fixtures
# Data Out:      Assertions on gate-blocked 400s and successful 200 completions
# Last Modified: 2026-03-29

"""Tests for sprint completion gates (DWB-087/088/089).

Projects have three boolean flags: force_headers, force_test_run, force_test_coverage.
When enabled, they block sprint completion (PATCH to status=completed) unless
the conditions are met.
"""


class TestProjectGateFields:
    """Verify the three boolean fields appear in project responses."""

    def test_create_project_defaults_gates_false(self, client):
        r = client.post("/api/projects", json={
            "prefix": "GATE",
            "name": "Gate Test",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["force_headers"] is False
        assert data["force_test_coverage"] is False
        assert data["force_test_run"] is False

    def test_create_project_with_gates_enabled(self, client):
        r = client.post("/api/projects", json={
            "prefix": "GTR",
            "name": "Gate True",
            "force_headers": True,
            "force_test_coverage": True,
            "force_test_run": True,
        })
        assert r.status_code == 201
        data = r.json()
        assert data["force_headers"] is True
        assert data["force_test_coverage"] is True
        assert data["force_test_run"] is True

    def test_get_project_includes_gate_fields(self, client, make_project):
        project = make_project()
        data = client.get(f"/api/projects/{project['id']}").json()
        assert "force_headers" in data
        assert "force_test_coverage" in data
        assert "force_test_run" in data

    def test_patch_toggles_gates(self, client, make_project):
        project = make_project()
        r = client.patch(f"/api/projects/{project['id']}", json={
            "force_test_run": True,
        })
        assert r.status_code == 200
        assert r.json()["force_test_run"] is True

        r = client.patch(f"/api/projects/{project['id']}", json={
            "force_test_run": False,
        })
        assert r.status_code == 200
        assert r.json()["force_test_run"] is False


class TestForceTestRunGate:
    """force_test_run=true requires at least one test result before sprint close."""

    def _make_gated_sprint(self, client, make_project, make_epic):
        project = client.post("/api/projects", json={
            "prefix": "FTR",
            "name": "Force Test Run",
            "force_test_run": True,
        }).json()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        return project, sprint

    def test_no_test_results_returns_400(self, client, make_project, make_epic):
        project, sprint = self._make_gated_sprint(client, make_project, make_epic)

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 400
        assert "force_test_run" in r.json()["detail"].lower()

    def test_with_test_results_closes_normally(
        self, client, make_project, make_epic, make_test_result
    ):
        project, sprint = self._make_gated_sprint(client, make_project, make_epic)

        # Add a test result for this project
        make_test_result(project_id=project["id"])

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_error_message_includes_project_prefix(
        self, client, make_project, make_epic
    ):
        project, sprint = self._make_gated_sprint(client, make_project, make_epic)

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 400
        assert project["prefix"] in r.json()["detail"]

    def test_gate_off_allows_close_without_tests(
        self, client, make_project, make_epic
    ):
        """force_test_run=false (default) allows close with no test results."""
        project = make_project()
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


class TestForceTestCoverageGate:
    """force_test_coverage=true requires all routers to have test files."""

    def _make_coverage_gated_sprint(self, client, make_epic):
        project = client.post("/api/projects", json={
            "prefix": "FTC",
            "name": "Force Test Coverage",
            "force_test_coverage": True,
        }).json()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        return project, sprint

    def test_all_routers_covered_allows_close(self, client, make_epic):
        """All routers now have test files, so coverage gate passes."""
        project, sprint = self._make_coverage_gated_sprint(client, make_epic)

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_gate_off_allows_close_with_gaps(self, client, make_project, make_epic):
        """force_test_coverage=false (default) allows close even with uncovered routers."""
        project = make_project()
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


class TestGateCombinations:
    """Test interactions when multiple gates are configured."""

    def test_both_gates_off_closes_freely(self, client, make_project, make_epic):
        project = make_project()
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

    def test_both_gates_on_test_run_fails_first(self, client, make_epic):
        """With both gates on, force_test_run is checked first."""
        project = client.post("/api/projects", json={
            "prefix": "BOTH",
            "name": "Both Gates",
            "force_test_run": True,
            "force_test_coverage": True,
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
        assert r.status_code == 400
        # force_test_run is checked before force_test_coverage
        assert "force_test_run" in r.json()["detail"].lower()

    def test_both_gates_satisfied_allows_close(
        self, client, make_epic, make_test_result
    ):
        """Both gates on, both satisfied — test run exists and all routers covered."""
        project = client.post("/api/projects", json={
            "prefix": "BG2",
            "name": "Both Gates 2",
            "force_test_run": True,
            "force_test_coverage": True,
        }).json()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        # Satisfy test_run gate
        make_test_result(project_id=project["id"])

        # Coverage gate is also satisfied since all routers have test files
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_toggle_gate_on_then_off_allows_close(
        self, client, make_project, make_epic
    ):
        """Enable gate, fail, disable gate, succeed."""
        project = make_project()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        # Enable force_test_run
        client.patch(f"/api/projects/{project['id']}", json={
            "force_test_run": True,
        })

        # Should fail
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 400

        # Disable the gate
        client.patch(f"/api/projects/{project['id']}", json={
            "force_test_run": False,
        })

        # Should now succeed
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200

    def test_non_completion_transitions_skip_gates(self, client, make_epic):
        """Moving to planned or active should not trigger gate checks."""
        project = client.post("/api/projects", json={
            "prefix": "SKP",
            "name": "Skip Gates",
            "force_test_run": True,
            "force_test_coverage": True,
        }).json()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        # Moving to planned should be fine even with all gates on
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "planned",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "planned"
