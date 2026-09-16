# Path:          tests/test_status.py
# File:          test_status.py
# Created:       2026-03-28
# Purpose:       Tests for system status and health check endpoint
# Caller:        pytest
# Callees:       GET /api/status, GET /api/status/test-coverage, POST /api/system/run-tests
# Data In:       None (stateless health check)
# Data Out:      Assertions on HTTP 200/400/404 and response shapes
# Last Modified: 2026-09-16 (DWB-571: run-tests guard-refusal tests; DWB-572:
#   smoke test for /status/test-coverage after its glob logic moved into
#   services/sprint.router_test_coverage)

"""Tests for GET /api/status."""


def test_status_returns_200(client):
    r = client.get("/api/status")
    assert r.status_code == 200


def test_status_response_shape(client):
    data = client.get("/api/status").json()
    assert isinstance(data["healthy"], bool)
    assert isinstance(data["active_agents"], int)
    assert isinstance(data["open_alerts"], int)
    assert isinstance(data["in_progress_tickets"], int)
    assert set(data.keys()) == {"healthy", "active_agents", "open_alerts", "in_progress_tickets", "infra_warnings"}


def test_status_healthy_is_true(client):
    data = client.get("/api/status").json()
    assert data["healthy"] is True


def test_status_counts_reflect_data(client, make_agent, make_ticket):
    """Create known data and verify status counts match."""
    # Create an active agent
    make_agent(is_active=True)
    # Create an in_progress ticket
    make_ticket(status="in_progress")

    data = client.get("/api/status").json()
    assert data["active_agents"] >= 1
    assert data["in_progress_tickets"] >= 1


class TestRunTestsGuard:
    """DWB-571: POST /system/run-tests refuses a project that isn't this
    server's own repo, BEFORE ever shelling out to run_tests.sh. These tests
    only exercise the refusal path - the success path would actually spawn
    a nested pytest run and is intentionally not covered here (see
    HANDOFF/ticket notes on that risk)."""

    def test_404_for_missing_project(self, client):
        r = client.post("/api/system/run-tests", params={"project_id": 999999})
        assert r.status_code == 404

    def test_400_for_project_with_no_repo_path(self, client, make_project):
        project = make_project()
        r = client.post("/api/system/run-tests", params={"project_id": project["id"]})
        assert r.status_code == 400
        assert project["prefix"] in r.json()["detail"]

    def test_400_for_project_with_unrelated_repo_path(
        self, client, make_project, tmp_path
    ):
        project = make_project(repo_path=str(tmp_path))
        r = client.post("/api/system/run-tests", params={"project_id": project["id"]})
        assert r.status_code == 400
        assert project["prefix"] in r.json()["detail"]


def test_test_coverage_returns_200_and_shape(client):
    """DWB-572: GET /status/test-coverage still reports DWB's OWN backend
    (unchanged) after the glob logic moved into services/sprint.router_test_coverage,
    shared with the per-project force_test_coverage gate."""
    r = client.get("/api/status/test-coverage")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for row in data:
        assert set(row.keys()) == {"router", "test_file", "covered"}
        assert isinstance(row["covered"], bool)
        # This is DWB's own status.py router; it must appear covered (this file).
    routers = {row["router"] for row in data}
    assert "status.py" in routers
