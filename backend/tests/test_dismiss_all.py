# Path:          tests/test_dismiss_all.py
# File:          test_dismiss_all.py
# Created:       2026-03-28
# Purpose:       Tests for bulk alert dismissal via POST /api/alerts/dismiss-all
# Caller:        pytest
# Callees:       POST /api/alerts, POST /api/alerts/dismiss-all
# Data In:       Factory-created projects, agents, alerts via conftest fixtures
# Data Out:      Assertions on dismissed count and alert status changes
# Last Modified: 2026-03-29

"""Tests for POST /api/alerts/dismiss-all (Sprint 12)."""


class TestDismissAll:
    def test_dismisses_open_alerts(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        # Create two open alerts
        a1 = client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "A1", "body": "B1",
        }).json()
        a2 = client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "A2", "body": "B2",
        }).json()

        r = client.post("/api/alerts/dismiss-all", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["dismissed"] >= 2

        # Verify both alerts are now acknowledged
        for aid in [a1["id"], a2["id"]]:
            alert = client.get(f"/api/alerts/{aid}").json()
            assert alert["status"] == "acknowledged"
            assert alert["resolved_at"] is not None

    def test_returns_dismissed_count(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        for i in range(3):
            client.post("/api/alerts", json={
                "project_id": project["id"], "raised_by_agent_id": agent["id"],
                "title": f"Alert {i}", "body": "B",
            })

        r = client.post("/api/alerts/dismiss-all", json={})
        assert r.status_code == 200
        assert r.json()["dismissed"] >= 3

    def test_returns_zero_when_no_open_alerts(self, client):
        # Dismiss everything first, then dismiss again
        client.post("/api/alerts/dismiss-all", json={})
        r = client.post("/api/alerts/dismiss-all", json={})
        assert r.status_code == 200
        assert r.json()["dismissed"] == 0

    def test_respects_project_id_filter(self, client, make_project, make_agent):
        p1 = make_project()
        p2 = make_project()
        agent = make_agent()
        # Create one alert per project
        a1 = client.post("/api/alerts", json={
            "project_id": p1["id"], "raised_by_agent_id": agent["id"],
            "title": "P1 Alert", "body": "B",
        }).json()
        a2 = client.post("/api/alerts", json={
            "project_id": p2["id"], "raised_by_agent_id": agent["id"],
            "title": "P2 Alert", "body": "B",
        }).json()

        # Dismiss only p1
        r = client.post("/api/alerts/dismiss-all", json={"project_id": p1["id"]})
        assert r.status_code == 200
        assert r.json()["dismissed"] >= 1

        # p1 alert dismissed, p2 still open
        assert client.get(f"/api/alerts/{a1['id']}").json()["status"] == "acknowledged"
        assert client.get(f"/api/alerts/{a2['id']}").json()["status"] == "open"

    def test_does_not_dismiss_already_resolved(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        a = client.post("/api/alerts", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
            "title": "Resolved", "body": "B",
        }).json()
        # Resolve it manually
        client.patch(f"/api/alerts/{a['id']}", json={"status": "resolved"})

        r = client.post("/api/alerts/dismiss-all", json={})
        # Should not count the already-resolved alert
        assert r.status_code == 200
        # The resolved alert should still be resolved, not acknowledged
        alert = client.get(f"/api/alerts/{a['id']}").json()
        assert alert["status"] == "resolved"
