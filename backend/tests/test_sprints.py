"""Tests for /api/sprints CRUD, filtering, and completion gates."""


class TestListSprints:
    def test_list_returns_200(self, client):
        r = client.get("/api/sprints")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_sprint(self, client, make_sprint):
        sprint = make_sprint()
        sprints = client.get("/api/sprints").json()
        ids = [s["id"] for s in sprints]
        assert sprint["id"] in ids

    def test_filter_by_project_id(self, client, make_project, make_sprint):
        p1 = make_project()
        p2 = make_project()
        make_sprint(project_id=p1["id"])
        make_sprint(project_id=p2["id"])
        sprints = client.get("/api/sprints", params={"project_id": p1["id"]}).json()
        assert len(sprints) >= 1
        assert all(s["project_id"] == p1["id"] for s in sprints)

    def test_filter_by_status(self, client, make_sprint):
        s1 = make_sprint(status="active")
        s2 = make_sprint(status="planned")
        active = client.get("/api/sprints", params={"status": "active"}).json()
        assert all(s["status"] == "active" for s in active)
        planned = client.get("/api/sprints", params={"status": "planned"}).json()
        assert all(s["status"] == "planned" for s in planned)


class TestGetSprint:
    def test_get_returns_200(self, client, make_sprint):
        sprint = make_sprint()
        r = client.get(f"/api/sprints/{sprint['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == sprint["id"]

    def test_get_response_shape(self, client, make_sprint):
        sprint = make_sprint()
        data = client.get(f"/api/sprints/{sprint['id']}").json()
        expected_keys = {
            "id", "project_id", "epic_id", "name", "goal",
            "sprint_number", "status", "start_date", "end_date",
            "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/sprints/999999")
        assert r.status_code == 404


class TestCreateSprint:
    def test_create_returns_201(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])
        r = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
        })
        assert r.status_code == 201
        assert r.json()["project_id"] == project["id"]
        assert r.json()["status"] == "planned"  # default

    def test_create_with_goal_generates_name(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])
        r = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "goal": "implement user authentication",
        })
        assert r.status_code == 201
        # Name should be generated from goal, not just "Sprint 1"
        assert r.json()["name"] != ""
        assert "Sprint 1" not in r.json()["name"] or "auth" in r.json()["name"].lower()

    def test_create_auto_assigns_epic(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])
        r = client.post("/api/sprints", json={
            "project_id": project["id"],
            "sprint_number": 1,
        })
        assert r.status_code == 201
        assert r.json()["epic_id"] == epic["id"]

    def test_create_nonexistent_project_returns_404(self, client):
        r = client.post("/api/sprints", json={
            "project_id": 999999,
            "sprint_number": 1,
        })
        assert r.status_code == 404


class TestUpdateSprint:
    def test_patch_updates_fields(self, client, make_sprint):
        sprint = make_sprint()
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "name": "Updated Sprint",
            "goal": "New goal",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "Updated Sprint"
        assert r.json()["goal"] == "New goal"

    def test_patch_status_transition(self, client, make_sprint):
        sprint = make_sprint(status="active")
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "planned",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "planned"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/sprints/999999", json={"name": "Nope"})
        assert r.status_code == 404


class TestDeleteSprint:
    def test_delete_returns_204(self, client, make_sprint):
        sprint = make_sprint()
        r = client.delete(f"/api/sprints/{sprint['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_sprint):
        sprint = make_sprint()
        client.delete(f"/api/sprints/{sprint['id']}")
        r = client.get(f"/api/sprints/{sprint['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/sprints/999999")
        assert r.status_code == 404


class TestSprintCompletionGates:
    """Completion gate tests specific to sprint CRUD (complementing test_completion_gates.py)."""

    def test_complete_sprint_without_gates(self, client, make_sprint):
        sprint = make_sprint(status="active")
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_force_test_run_blocks_completion(self, client, make_epic):
        project = client.post("/api/projects", json={
            "prefix": "STR",
            "name": "Sprint Test Run",
            "force_test_run": True,
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
        assert "force_test_run" in r.json()["detail"].lower()

    def test_force_test_run_passes_with_results(
        self, client, make_epic, make_test_result
    ):
        project = client.post("/api/projects", json={
            "prefix": "STP",
            "name": "Sprint Test Pass",
            "force_test_run": True,
        }).json()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        make_test_result(project_id=project["id"])
        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"
