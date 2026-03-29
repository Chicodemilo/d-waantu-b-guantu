"""Tests for DWB-076: auto-test-ticket and alerts on sprint close.

When a sprint is PATCHed to status=completed, the system should:
1. Create info alerts for project agents with roles in _ALERT_ROLES (team-lead, pm, tester)
2. If another active sprint exists and a tester agent is assigned, auto-create a test ticket
"""

import pytest


@pytest.fixture
def sprint_close_project(client, make_project, make_epic):
    """Set up a project with agents assigned in the required roles."""
    project = make_project()
    epic = make_epic(project_id=project["id"])

    agents = {}
    for role in ("team-lead", "pm", "tester"):
        agent = client.post("/api/agents", json={
            "name": f"{role.title()} Agent",
            "role": role,
            "api_key": f"sc-{role}-{project['id']}",
        }).json()
        client.post("/api/project-agents", json={
            "project_id": project["id"],
            "agent_id": agent["id"],
        })
        agents[role] = agent

    return {"project": project, "epic": epic, "agents": agents}


class TestSprintCloseAlerts:
    def test_closing_sprint_creates_alerts(self, client, sprint_close_project):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        alerts_before = client.get("/api/alerts", params={
            "project_id": ctx["project"]["id"],
        }).json()

        r = client.patch(f"/api/sprints/{sprint['id']}", json={
            "status": "completed",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

        alerts_after = client.get("/api/alerts", params={
            "project_id": ctx["project"]["id"],
        }).json()
        new_alerts = [
            a for a in alerts_after
            if a["id"] not in {al["id"] for al in alerts_before}
        ]
        # One alert per role (team-lead, pm, tester)
        assert len(new_alerts) == 3
        assert all(a["severity"] == "info" for a in new_alerts)
        assert all("tests needed" in a["title"].lower() for a in new_alerts)

    def test_alert_mentions_sprint_name(self, client, sprint_close_project):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 5,
            "status": "active",
            "name": "Auth Rework",
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        alerts = client.get("/api/alerts", params={
            "project_id": ctx["project"]["id"],
        }).json()
        sprint_alerts = [
            a for a in alerts
            if "Auth Rework" in a.get("title", "") or "Auth Rework" in a.get("body", "")
        ]
        assert len(sprint_alerts) >= 1

    def test_non_completed_status_does_not_create_alerts(
        self, client, sprint_close_project
    ):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 3,
            "status": "active",
        }).json()

        alerts_before = client.get("/api/alerts", params={
            "project_id": ctx["project"]["id"],
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "planned"})

        alerts_after = client.get("/api/alerts", params={
            "project_id": ctx["project"]["id"],
        }).json()
        new_alerts = [
            a for a in alerts_after
            if a["id"] not in {al["id"] for al in alerts_before}
        ]
        assert len(new_alerts) == 0

    def test_no_alerts_when_no_agents_assigned(self, client, make_project, make_epic):
        """Project with no agents should produce no alerts on sprint close."""
        project = make_project()
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"],
            "epic_id": epic["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        alerts_before = client.get("/api/alerts", params={
            "project_id": project["id"],
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        alerts_after = client.get("/api/alerts", params={
            "project_id": project["id"],
        }).json()
        new_alerts = [
            a for a in alerts_after
            if a["id"] not in {al["id"] for al in alerts_before}
        ]
        assert len(new_alerts) == 0


class TestSprintCloseAutoTicket:
    def test_closing_sprint_with_next_active_creates_ticket(
        self, client, sprint_close_project
    ):
        ctx = sprint_close_project
        s1 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
            "name": "Feature Sprint",
        }).json()
        s2 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 2,
            "status": "active",
        }).json()

        client.patch(f"/api/sprints/{s1['id']}", json={"status": "completed"})

        tickets = client.get("/api/tickets", params={
            "sprint_id": s2["id"],
        }).json()
        test_tickets = [t for t in tickets if "test" in t["title"].lower()]
        assert len(test_tickets) >= 1
        tt = test_tickets[0]
        assert tt["status"] == "todo"
        assert tt["ticket_type"] == "task"
        assert "Feature Sprint" in tt["title"] or "S1" in tt["title"]
        assert tt["assigned_agent_id"] == ctx["agents"]["tester"]["id"]

    def test_closing_sprint_without_next_active_no_ticket(
        self, client, sprint_close_project
    ):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        tickets = client.get("/api/tickets", params={
            "project_id": ctx["project"]["id"],
        }).json()
        test_tickets = [t for t in tickets if "test" in t["title"].lower()]
        assert len(test_tickets) == 0

    def test_no_ticket_when_no_tester_assigned(self, client, make_project, make_epic):
        """If no tester agent is assigned, no auto-ticket should be created."""
        project = make_project()
        epic = make_epic(project_id=project["id"])

        # Only assign a team-lead, no tester
        agent = client.post("/api/agents", json={
            "name": "TL Only", "role": "team-lead",
            "api_key": f"tl-only-{project['id']}",
        }).json()
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": agent["id"],
        })

        s1 = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 1, "status": "active",
        }).json()
        s2 = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 2, "status": "active",
        }).json()

        client.patch(f"/api/sprints/{s1['id']}", json={"status": "completed"})

        tickets = client.get("/api/tickets", params={
            "sprint_id": s2["id"],
        }).json()
        test_tickets = [t for t in tickets if "test" in t["title"].lower()]
        assert len(test_tickets) == 0

    def test_auto_ticket_has_correct_ticket_key(
        self, client, sprint_close_project
    ):
        ctx = sprint_close_project
        s1 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        s2 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 2,
            "status": "active",
        }).json()

        client.patch(f"/api/sprints/{s1['id']}", json={"status": "completed"})

        tickets = client.get("/api/tickets", params={
            "sprint_id": s2["id"],
        }).json()
        test_tickets = [t for t in tickets if "test" in t["title"].lower()]
        assert len(test_tickets) >= 1
        assert test_tickets[0]["ticket_key"].startswith(ctx["project"]["prefix"])

    def test_closing_already_completed_sprint_no_duplicate(
        self, client, sprint_close_project
    ):
        ctx = sprint_close_project
        s1 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        s2 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 2,
            "status": "active",
        }).json()

        # Close once
        client.patch(f"/api/sprints/{s1['id']}", json={"status": "completed"})
        tickets_after_first = client.get("/api/tickets", params={
            "sprint_id": s2["id"],
        }).json()

        # Close again (already completed -> completed, should be a no-op)
        client.patch(f"/api/sprints/{s1['id']}", json={"status": "completed"})
        tickets_after_second = client.get("/api/tickets", params={
            "sprint_id": s2["id"],
        }).json()

        assert len(tickets_after_second) == len(tickets_after_first)
