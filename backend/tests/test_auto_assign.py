"""Tests for auto-assign hierarchy (Sprints 12-13).

- Ticket without sprint_id → auto-assigns to active sprint
- Sprint without epic_id → auto-assigns to active/open epic
"""


class TestTicketAutoAssignSprint:
    def test_auto_assigns_to_active_sprint(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        ticket = client.post("/api/tickets", json={
            "project_id": project["id"],
            "ticket_number": 1,
            "ticket_key": "AUTO-001",
            "title": "Auto assign test",
        })
        assert ticket.status_code == 201
        assert ticket.json()["sprint_id"] == sprint["id"]

    def test_auto_assigns_epic_from_sprint(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        ticket = client.post("/api/tickets", json={
            "project_id": project["id"],
            "ticket_number": 2,
            "ticket_key": "AUTO-002",
            "title": "Auto epic from sprint",
        })
        assert ticket.status_code == 201
        assert ticket.json()["epic_id"] == epic["id"]

    def test_explicit_sprint_id_is_respected(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])
        s1 = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 1, "status": "active",
        }).json()
        s2 = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 2, "status": "planned",
        }).json()

        ticket = client.post("/api/tickets", json={
            "project_id": project["id"],
            "sprint_id": s2["id"],
            "ticket_number": 3,
            "ticket_key": "AUTO-003",
            "title": "Explicit sprint",
        })
        assert ticket.status_code == 201
        assert ticket.json()["sprint_id"] == s2["id"]

    def test_no_active_sprint_returns_400(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])
        # Create only a planned sprint (not active)
        client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 1, "status": "planned",
        })

        r = client.post("/api/tickets", json={
            "project_id": project["id"],
            "ticket_number": 4,
            "ticket_key": "AUTO-004",
            "title": "Should fail",
        })
        assert r.status_code == 400


class TestSprintAutoAssignEpic:
    def test_auto_assigns_to_active_epic(self, client, make_project, make_epic):
        project = make_project()
        epic = make_epic(project_id=project["id"])

        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "sprint_number": 1,
        })
        assert sprint.status_code == 201
        assert sprint.json()["epic_id"] == epic["id"]

    def test_accepts_open_or_in_progress_epic(self, client, make_project):
        project = make_project()
        # Create both open and in_progress epics
        open_epic = client.post("/api/epics", json={
            "project_id": project["id"], "name": "Open Epic",
        }).json()
        ip_epic = client.post("/api/epics", json={
            "project_id": project["id"], "name": "IP Epic", "status": "in_progress",
        }).json()

        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "sprint_number": 1,
        })
        assert sprint.status_code == 201
        # Should pick one of the open/in_progress epics (most recent by created_at)
        assert sprint.json()["epic_id"] in [open_epic["id"], ip_epic["id"]]

    def test_explicit_epic_id_is_respected(self, client, make_project, make_epic):
        project = make_project()
        e1 = make_epic(project_id=project["id"])
        e2 = make_epic(project_id=project["id"])

        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": e1["id"],
            "sprint_number": 1,
        })
        assert sprint.status_code == 201
        assert sprint.json()["epic_id"] == e1["id"]

    def test_no_open_epic_returns_400(self, client, make_project):
        project = make_project()
        # No epics at all
        r = client.post("/api/sprints", json={
            "project_id": project["id"],
            "sprint_number": 1,
        })
        assert r.status_code == 400
