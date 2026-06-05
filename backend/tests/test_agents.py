# Path:          tests/test_agents.py
# File:          test_agents.py
# Created:       2026-03-28
# Purpose:       Full CRUD + filtering tests for /api/agents
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/agents, GET /api/agents/:id
# Data In:       Factory-created agents via conftest fixtures
# Data Out:      Assertions on HTTP status codes and JSON response shapes
# Last Modified: 2026-03-29

"""Tests for /api/agents CRUD and filtering."""


class TestListAgents:
    def test_list_returns_200(self, client):
        r = client.get("/api/agents")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_agent(self, client, make_agent):
        agent = make_agent()
        agents = client.get("/api/agents").json()
        ids = [a["id"] for a in agents]
        assert agent["id"] in ids

    def test_filter_by_role(self, client, make_agent):
        make_agent(role="developer")
        make_agent(role="tester")
        devs = client.get("/api/agents", params={"role": "developer"}).json()
        assert all(a["role"] == "developer" for a in devs)
        testers = client.get("/api/agents", params={"role": "tester"}).json()
        assert all(a["role"] == "tester" for a in testers)

    def test_filter_by_is_active(self, client, make_agent):
        active = make_agent()
        inactive = make_agent()
        client.patch(f"/api/agents/{inactive['id']}", json={"is_active": False})

        active_agents = client.get("/api/agents", params={"is_active": True}).json()
        active_ids = [a["id"] for a in active_agents]
        assert active["id"] in active_ids
        assert inactive["id"] not in active_ids

        inactive_agents = client.get("/api/agents", params={"is_active": False}).json()
        inactive_ids = [a["id"] for a in inactive_agents]
        assert inactive["id"] in inactive_ids


class TestGetAgent:
    def test_get_returns_200(self, client, make_agent):
        agent = make_agent()
        r = client.get(f"/api/agents/{agent['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == agent["id"]

    def test_get_response_shape(self, client, make_agent):
        agent = make_agent()
        data = client.get(f"/api/agents/{agent['id']}").json()
        expected_keys = {
            "id", "project_id", "name", "description", "role", "api_key",
            "is_active", "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/agents/999999")
        assert r.status_code == 404


class TestCreateAgent:
    def test_create_returns_201(self, client, make_project):
        project = make_project()
        r = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "New Agent",
            "role": "developer",
            "api_key": "new-key-unique",
        })
        assert r.status_code == 201
        assert r.json()["name"] == "New Agent"
        assert r.json()["role"] == "developer"
        assert r.json()["is_active"] is True  # default

    def test_create_with_all_fields(self, client, make_project):
        project = make_project()
        r = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": "Full Agent",
            "description": "A described agent",
            "role": "pm",
            "api_key": "full-agent-key",
            "is_active": False,
        })
        assert r.status_code == 201
        data = r.json()
        assert data["description"] == "A described agent"
        assert data["is_active"] is False


class TestUpdateAgent:
    def test_patch_updates_fields(self, client, make_agent):
        agent = make_agent()
        r = client.patch(f"/api/agents/{agent['id']}", json={
            "name": "Updated Agent",
            "role": "tester",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "Updated Agent"
        assert r.json()["role"] == "tester"

    def test_patch_toggle_is_active(self, client, make_agent):
        agent = make_agent()
        r = client.patch(f"/api/agents/{agent['id']}", json={"is_active": False})
        assert r.status_code == 200
        assert r.json()["is_active"] is False

        r = client.patch(f"/api/agents/{agent['id']}", json={"is_active": True})
        assert r.status_code == 200
        assert r.json()["is_active"] is True

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/agents/999999", json={"name": "Nope"})
        assert r.status_code == 404


class TestDeleteAgent:
    def test_delete_returns_204(self, client, make_agent):
        agent = make_agent()
        r = client.delete(f"/api/agents/{agent['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_agent):
        agent = make_agent()
        client.delete(f"/api/agents/{agent['id']}")
        r = client.get(f"/api/agents/{agent['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/agents/999999")
        assert r.status_code == 404
