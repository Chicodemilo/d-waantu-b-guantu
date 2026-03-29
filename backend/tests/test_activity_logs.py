"""Tests for /api/activity-logs endpoints."""


class TestListActivityLogs:
    def test_list_returns_200(self, client):
        r = client.get("/api/activity-logs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_log(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/activity-logs", json={
            "project_id": project["id"],
            "agent_id": agent["id"],
            "entity_type": "ticket",
            "entity_id": 1,
            "action": "created",
        }).json()
        logs = client.get("/api/activity-logs").json()
        ids = [l["id"] for l in logs]
        assert created["id"] in ids

    def test_filter_by_project_id(self, client, make_project, make_agent):
        p1 = make_project()
        p2 = make_project()
        agent = make_agent()
        client.post("/api/activity-logs", json={
            "project_id": p1["id"], "agent_id": agent["id"],
            "entity_type": "ticket", "entity_id": 1, "action": "created",
        })
        client.post("/api/activity-logs", json={
            "project_id": p2["id"], "agent_id": agent["id"],
            "entity_type": "ticket", "entity_id": 2, "action": "created",
        })
        logs = client.get("/api/activity-logs", params={"project_id": p1["id"]}).json()
        assert all(l["project_id"] == p1["id"] for l in logs)

    def test_filter_by_agent_id(self, client, make_project, make_agent):
        project = make_project()
        a1 = make_agent()
        a2 = make_agent()
        client.post("/api/activity-logs", json={
            "project_id": project["id"], "agent_id": a1["id"],
            "entity_type": "ticket", "entity_id": 1, "action": "created",
        })
        client.post("/api/activity-logs", json={
            "project_id": project["id"], "agent_id": a2["id"],
            "entity_type": "ticket", "entity_id": 2, "action": "updated",
        })
        logs = client.get("/api/activity-logs", params={"agent_id": a1["id"]}).json()
        assert all(l["agent_id"] == a1["id"] for l in logs)

    def test_filter_by_entity_type(self, client, make_project):
        project = make_project()
        client.post("/api/activity-logs", json={
            "project_id": project["id"],
            "entity_type": "ticket", "entity_id": 1, "action": "created",
        })
        client.post("/api/activity-logs", json={
            "project_id": project["id"],
            "entity_type": "sprint", "entity_id": 1, "action": "completed",
        })
        logs = client.get("/api/activity-logs", params={"entity_type": "ticket"}).json()
        assert all(l["entity_type"] == "ticket" for l in logs)


class TestGetActivityLog:
    def test_get_returns_200(self, client, make_project):
        project = make_project()
        created = client.post("/api/activity-logs", json={
            "project_id": project["id"],
            "entity_type": "ticket", "entity_id": 1, "action": "created",
        }).json()
        r = client.get(f"/api/activity-logs/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_response_shape(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        created = client.post("/api/activity-logs", json={
            "project_id": project["id"], "agent_id": agent["id"],
            "entity_type": "ticket", "entity_id": 1, "action": "created",
            "details": "some detail",
        }).json()
        data = client.get(f"/api/activity-logs/{created['id']}").json()
        expected_keys = {
            "id", "project_id", "agent_id", "entity_type", "entity_id",
            "action", "details", "created_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/activity-logs/999999")
        assert r.status_code == 404


class TestCreateActivityLog:
    def test_create_returns_201(self, client, make_project):
        project = make_project()
        r = client.post("/api/activity-logs", json={
            "project_id": project["id"],
            "entity_type": "ticket",
            "entity_id": 1,
            "action": "created",
        })
        assert r.status_code == 201
        assert r.json()["entity_type"] == "ticket"
        assert r.json()["action"] == "created"

    def test_create_with_all_fields(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/activity-logs", json={
            "project_id": project["id"],
            "agent_id": agent["id"],
            "entity_type": "sprint",
            "entity_id": 5,
            "action": "completed",
            "details": "Sprint finished successfully",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["agent_id"] == agent["id"]
        assert data["details"] == "Sprint finished successfully"

    def test_create_without_agent_id(self, client, make_project):
        project = make_project()
        r = client.post("/api/activity-logs", json={
            "project_id": project["id"],
            "entity_type": "ticket",
            "entity_id": 1,
            "action": "auto-created",
        })
        assert r.status_code == 201
        assert r.json()["agent_id"] is None
