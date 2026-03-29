"""Tests for /api/epics CRUD and filtering."""


class TestListEpics:
    def test_list_returns_200(self, client):
        r = client.get("/api/epics")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_epic(self, client, make_epic):
        epic = make_epic()
        epics = client.get("/api/epics").json()
        ids = [e["id"] for e in epics]
        assert epic["id"] in ids

    def test_filter_by_project_id(self, client, make_project, make_epic):
        p1 = make_project()
        p2 = make_project()
        make_epic(project_id=p1["id"])
        make_epic(project_id=p2["id"])
        epics = client.get("/api/epics", params={"project_id": p1["id"]}).json()
        assert len(epics) >= 1
        assert all(e["project_id"] == p1["id"] for e in epics)

    def test_filter_by_status(self, client, make_project, make_epic):
        project = make_project()
        make_epic(project_id=project["id"], status="open")
        e2 = make_epic(project_id=project["id"])
        client.patch(f"/api/epics/{e2['id']}", json={"status": "completed"})

        open_epics = client.get("/api/epics", params={
            "project_id": project["id"], "status": "open",
        }).json()
        assert all(e["status"] == "open" for e in open_epics)

        completed_epics = client.get("/api/epics", params={
            "project_id": project["id"], "status": "completed",
        }).json()
        assert all(e["status"] == "completed" for e in completed_epics)


class TestGetEpic:
    def test_get_returns_200(self, client, make_epic):
        epic = make_epic()
        r = client.get(f"/api/epics/{epic['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == epic["id"]

    def test_get_response_shape(self, client, make_epic):
        epic = make_epic()
        data = client.get(f"/api/epics/{epic['id']}").json()
        expected_keys = {
            "id", "project_id", "name", "description", "status",
            "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/epics/999999")
        assert r.status_code == 404


class TestCreateEpic:
    def test_create_returns_201(self, client, make_project):
        project = make_project()
        r = client.post("/api/epics", json={
            "project_id": project["id"],
            "name": "New Epic",
        })
        assert r.status_code == 201
        assert r.json()["name"] == "New Epic"
        assert r.json()["status"] == "open"  # default

    def test_create_with_all_fields(self, client, make_project):
        project = make_project()
        r = client.post("/api/epics", json={
            "project_id": project["id"],
            "name": "Full Epic",
            "description": "Epic with description",
            "status": "in_progress",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["description"] == "Epic with description"
        assert data["status"] == "in_progress"


class TestUpdateEpic:
    def test_patch_updates_fields(self, client, make_epic):
        epic = make_epic()
        r = client.patch(f"/api/epics/{epic['id']}", json={
            "name": "Updated Epic",
            "status": "in_progress",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "Updated Epic"
        assert r.json()["status"] == "in_progress"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/epics/999999", json={"name": "Nope"})
        assert r.status_code == 404


class TestDeleteEpic:
    def test_delete_returns_204(self, client, make_epic):
        epic = make_epic()
        r = client.delete(f"/api/epics/{epic['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_epic):
        epic = make_epic()
        client.delete(f"/api/epics/{epic['id']}")
        r = client.get(f"/api/epics/{epic['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/epics/999999")
        assert r.status_code == 404
