"""Tests for /api/instructions sync-check and sync endpoints."""


class TestSyncCheck:
    def test_sync_check_returns_200(self, client):
        r = client.get("/api/instructions/sync-check")
        assert r.status_code == 200

    def test_sync_check_response_shape(self, client):
        data = client.get("/api/instructions/sync-check").json()
        assert "matched" in data
        assert "memory_only" in data
        assert "db_only" in data
        assert "in_sync" in data
        assert isinstance(data["matched"], list)
        assert isinstance(data["memory_only"], list)
        assert isinstance(data["db_only"], list)
        assert isinstance(data["in_sync"], bool)

    def test_sync_check_db_only_includes_instructions(self, client, make_instruction):
        inst = make_instruction(scope="global", title="DB Only Instruction")
        data = client.get("/api/instructions/sync-check").json()
        db_only_ids = [d["id"] for d in data["db_only"]]
        assert inst["id"] in db_only_ids


class TestSync:
    def test_sync_returns_201(self, client):
        r = client.post("/api/instructions/sync")
        assert r.status_code == 201
        assert isinstance(r.json(), list)


class TestInstructionsCRUD:
    def test_list_returns_200(self, client):
        r = client.get("/api/instructions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_returns_201(self, client):
        r = client.post("/api/instructions", json={
            "scope": "global",
            "title": "Test Global Instruction",
            "body": "Do the thing.",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["scope"] == "global"
        assert data["title"] == "Test Global Instruction"
        assert data["body"] == "Do the thing."

    def test_create_project_scoped(self, client, make_project):
        project = make_project()
        r = client.post("/api/instructions", json={
            "scope": "project",
            "project_id": project["id"],
            "title": "Project Instruction",
            "body": "Project specific.",
        })
        assert r.status_code == 201
        assert r.json()["project_id"] == project["id"]
        assert r.json()["scope"] == "project"

    def test_get_returns_200(self, client, make_instruction):
        inst = make_instruction()
        r = client.get(f"/api/instructions/{inst['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == inst["id"]

    def test_get_response_shape(self, client, make_instruction):
        inst = make_instruction()
        data = client.get(f"/api/instructions/{inst['id']}").json()
        expected_keys = {
            "id", "scope", "project_id", "agent_id",
            "title", "body", "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/instructions/999999")
        assert r.status_code == 404

    def test_patch_updates_fields(self, client, make_instruction):
        inst = make_instruction()
        r = client.patch(f"/api/instructions/{inst['id']}", json={
            "title": "Updated Title",
            "body": "Updated body.",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Title"
        assert r.json()["body"] == "Updated body."

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/instructions/999999", json={"title": "Nope"})
        assert r.status_code == 404

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

    def test_filter_by_scope(self, client, make_instruction):
        make_instruction(scope="global")
        make_instruction(scope="global")

        filtered = client.get("/api/instructions", params={"scope": "global"}).json()
        assert all(i["scope"] == "global" for i in filtered)

    def test_filter_by_project_id(self, client, make_project, make_instruction):
        p1 = make_project()
        p2 = make_project()
        make_instruction(scope="project", project_id=p1["id"])
        make_instruction(scope="project", project_id=p2["id"])

        filtered = client.get("/api/instructions", params={"project_id": p1["id"]}).json()
        assert all(i["project_id"] == p1["id"] for i in filtered)
