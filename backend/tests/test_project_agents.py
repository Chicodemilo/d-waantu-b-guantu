"""Tests for /api/project-agents CRUD and filtering."""


class TestListProjectAgents:
    def test_list_returns_200(self, client):
        r = client.get("/api/project-agents")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_assignment(self, client, make_project_agent):
        pa = make_project_agent()
        results = client.get("/api/project-agents").json()
        ids = [x["id"] for x in results]
        assert pa["id"] in ids

    def test_filter_by_project_id(self, client, make_project, make_agent, make_project_agent):
        p1 = make_project()
        p2 = make_project()
        a1 = make_agent()
        a2 = make_agent()
        pa1 = make_project_agent(project_id=p1["id"], agent_id=a1["id"])
        pa2 = make_project_agent(project_id=p2["id"], agent_id=a2["id"])

        filtered = client.get("/api/project-agents", params={"project_id": p1["id"]}).json()
        ids = [x["id"] for x in filtered]
        assert pa1["id"] in ids
        assert pa2["id"] not in ids

    def test_filter_by_agent_id(self, client, make_project, make_agent, make_project_agent):
        p1 = make_project()
        p2 = make_project()
        agent = make_agent()
        other_agent = make_agent()
        pa1 = make_project_agent(project_id=p1["id"], agent_id=agent["id"])
        pa2 = make_project_agent(project_id=p2["id"], agent_id=other_agent["id"])

        filtered = client.get("/api/project-agents", params={"agent_id": agent["id"]}).json()
        ids = [x["id"] for x in filtered]
        assert pa1["id"] in ids
        assert pa2["id"] not in ids


class TestGetProjectAgent:
    def test_get_returns_200(self, client, make_project_agent):
        pa = make_project_agent()
        r = client.get(f"/api/project-agents/{pa['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == pa["id"]

    def test_get_response_shape(self, client, make_project_agent):
        pa = make_project_agent()
        data = client.get(f"/api/project-agents/{pa['id']}").json()
        expected_keys = {"id", "project_id", "agent_id", "assigned_at"}
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/project-agents/999999")
        assert r.status_code == 404


class TestCreateProjectAgent:
    def test_create_returns_201(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/project-agents", json={
            "project_id": project["id"],
            "agent_id": agent["id"],
        })
        assert r.status_code == 201
        data = r.json()
        assert data["project_id"] == project["id"]
        assert data["agent_id"] == agent["id"]
        assert "assigned_at" in data


class TestDeleteProjectAgent:
    def test_delete_returns_204(self, client, make_project_agent):
        pa = make_project_agent()
        r = client.delete(f"/api/project-agents/{pa['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_project_agent):
        pa = make_project_agent()
        client.delete(f"/api/project-agents/{pa['id']}")
        r = client.get(f"/api/project-agents/{pa['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/project-agents/999999")
        assert r.status_code == 404
