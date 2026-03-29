# Path:          tests/test_alerts.py
# File:          test_alerts.py
# Created:       2026-03-28
# Purpose:       CRUD + filtering tests for /api/alerts
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/alerts, GET /api/alerts/:id
# Data In:       Factory-created projects, agents via conftest fixtures
# Data Out:      Assertions on HTTP status codes and JSON response shapes
# Last Modified: 2026-03-29

"""Tests for /api/alerts CRUD, filtering, and run-tests endpoint."""


class TestListAlerts:
    def test_list_returns_200(self, client):
        r = client.get("/api/alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_alert(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Test",
            "body": "Body",
        }).json()
        alerts = client.get("/api/alerts").json()
        ids = [a["id"] for a in alerts]
        assert created["id"] in ids

    def test_filter_by_project_id(self, client, make_project, make_agent):
        p1 = make_project()
        p2 = make_project()
        agent = make_agent()
        a1 = client.post("/api/alerts", json={
            "project_id": p1["id"], "raised_by_agent_id": agent["id"],
            "title": "A1", "body": "B1",
        }).json()
        a2 = client.post("/api/alerts", json={
            "project_id": p2["id"], "raised_by_agent_id": agent["id"],
            "title": "A2", "body": "B2",
        }).json()
        filtered = client.get("/api/alerts", params={"project_id": p1["id"]}).json()
        ids = [a["id"] for a in filtered]
        assert a1["id"] in ids
        assert a2["id"] not in ids

    def test_filter_by_severity(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "Info", "body": "B", "severity": "info",
        })
        client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "Warn", "body": "B", "severity": "warning",
        })
        filtered = client.get("/api/alerts", params={"severity": "info"}).json()
        assert all(a["severity"] == "info" for a in filtered)

    def test_filter_by_status(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        a = client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "T", "body": "B",
        }).json()
        client.patch(f"/api/alerts/{a['id']}", json={"status": "resolved"})
        open_alerts = client.get("/api/alerts", params={"status": "open"}).json()
        assert a["id"] not in [al["id"] for al in open_alerts]


class TestGetAlert:
    def test_get_returns_200(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Test", "body": "Body",
        }).json()
        r = client.get(f"/api/alerts/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_response_shape(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Test", "body": "Body",
        }).json()
        data = client.get(f"/api/alerts/{created['id']}").json()
        expected_keys = {
            "id", "project_id", "raised_by_agent_id", "ticket_id",
            "title", "body", "severity", "status",
            "created_at", "resolved_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/alerts/999999")
        assert r.status_code == 404


class TestCreateAlert:
    def test_create_returns_201(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "New Alert",
            "body": "Alert body",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "New Alert"
        assert data["severity"] == "info"
        assert data["status"] == "open"

    def test_create_with_severity(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Warning", "body": "Body",
            "severity": "warning",
        })
        assert r.status_code == 201
        assert r.json()["severity"] == "warning"


class TestUpdateAlert:
    def test_patch_status(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "T", "body": "B",
        }).json()
        r = client.patch(f"/api/alerts/{created['id']}", json={"status": "resolved"})
        assert r.status_code == 200
        assert r.json()["status"] == "resolved"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/alerts/999999", json={"status": "resolved"})
        assert r.status_code == 404


class TestRunTests:
    def test_run_tests_returns_201(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts/run-tests", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
        })
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "Test run requested"
        assert data["severity"] == "info"
        assert data["status"] == "open"
        assert project["name"] in data["body"]

    def test_run_tests_with_explicit_agent_id(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts/run-tests", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
        })
        assert r.status_code == 201
        assert r.json()["raised_by_agent_id"] == agent["id"]

    def test_run_tests_nonexistent_project_returns_404(self, client):
        r = client.post("/api/alerts/run-tests", json={"project_id": 999999})
        assert r.status_code == 404
