"""Tests for /api/instructions CRUD and filtering."""


class TestListInstructions:
    def test_list_returns_200(self, client):
        r = client.get("/api/instructions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_instruction(self, client, make_instruction):
        inst = make_instruction()
        instructions = client.get("/api/instructions").json()
        ids = [i["id"] for i in instructions]
        assert inst["id"] in ids

    def test_filter_by_scope(self, client, make_instruction, make_project):
        project = make_project()
        make_instruction(scope="global")
        make_instruction(scope="project", project_id=project["id"])
        global_insts = client.get("/api/instructions", params={"scope": "global"}).json()
        assert all(i["scope"] == "global" for i in global_insts)

    def test_filter_by_project_id(self, client, make_instruction, make_project):
        p1 = make_project()
        p2 = make_project()
        make_instruction(scope="project", project_id=p1["id"])
        make_instruction(scope="project", project_id=p2["id"])
        insts = client.get("/api/instructions", params={"project_id": p1["id"]}).json()
        assert all(i["project_id"] == p1["id"] for i in insts)

    def test_filter_by_agent_id(self, client, make_instruction, make_agent):
        a1 = make_agent()
        a2 = make_agent()
        make_instruction(scope="agent", agent_id=a1["id"])
        make_instruction(scope="agent", agent_id=a2["id"])
        insts = client.get("/api/instructions", params={"agent_id": a1["id"]}).json()
        assert all(i["agent_id"] == a1["id"] for i in insts)


class TestGetInstruction:
    def test_get_returns_200(self, client, make_instruction):
        inst = make_instruction()
        r = client.get(f"/api/instructions/{inst['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == inst["id"]

    def test_get_response_shape(self, client, make_instruction):
        inst = make_instruction()
        data = client.get(f"/api/instructions/{inst['id']}").json()
        expected_keys = {
            "id", "scope", "project_id", "agent_id", "title", "body",
            "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/instructions/999999")
        assert r.status_code == 404


class TestCreateInstruction:
    def test_create_returns_201(self, client):
        r = client.post("/api/instructions", json={
            "scope": "global",
            "title": "New Instruction",
            "body": "Do the thing",
        })
        assert r.status_code == 201
        assert r.json()["title"] == "New Instruction"
        assert r.json()["scope"] == "global"

    def test_create_project_scoped(self, client, make_project):
        project = make_project()
        r = client.post("/api/instructions", json={
            "scope": "project",
            "project_id": project["id"],
            "title": "Project Rule",
            "body": "Follow this rule",
        })
        assert r.status_code == 201
        assert r.json()["project_id"] == project["id"]
        assert r.json()["scope"] == "project"

    def test_create_agent_scoped(self, client, make_agent):
        agent = make_agent()
        r = client.post("/api/instructions", json={
            "scope": "agent",
            "agent_id": agent["id"],
            "title": "Agent Rule",
            "body": "Agent-specific instruction",
        })
        assert r.status_code == 201
        assert r.json()["agent_id"] == agent["id"]
        assert r.json()["scope"] == "agent"


class TestUpdateInstruction:
    def test_patch_updates_fields(self, client, make_instruction):
        inst = make_instruction()
        r = client.patch(f"/api/instructions/{inst['id']}", json={
            "title": "Updated Title",
            "body": "Updated body",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Title"
        assert r.json()["body"] == "Updated body"

    def test_patch_change_scope(self, client, make_instruction, make_project):
        inst = make_instruction(scope="global")
        project = make_project()
        r = client.patch(f"/api/instructions/{inst['id']}", json={
            "scope": "project",
            "project_id": project["id"],
        })
        assert r.status_code == 200
        assert r.json()["scope"] == "project"
        assert r.json()["project_id"] == project["id"]

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/instructions/999999", json={"title": "Nope"})
        assert r.status_code == 404


class TestDeleteInstruction:
    def test_delete_returns_204(self, client, make_instruction):
        inst = make_instruction()
        r = client.delete(f"/api/instructions/{inst['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_instruction):
        inst = make_instruction()
        client.delete(f"/api/instructions/{inst['id']}")
        r = client.get(f"/api/instructions/{inst['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/instructions/999999")
        assert r.status_code == 404
