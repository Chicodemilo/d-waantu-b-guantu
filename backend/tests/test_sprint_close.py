# Path:          tests/test_sprint_close.py
# File:          test_sprint_close.py
# Created:       2026-03-28
# Purpose:       Tests for auto-alert and auto-test-ticket on sprint completion
# Caller:        pytest
# Callees:       PATCH /api/sprints, GET /api/alerts, GET /api/tickets
# Data In:       Factory-created projects, epics, sprints, agents via conftest fixtures
# Data Out:      Assertions on auto-created alerts and test tickets
# Last Modified: 2026-09-16 (DWB-566: mint targets the closing sprint, backlog, unassigned)

"""Tests for auto-test-ticket and alerts on sprint close (DWB-076, DWB-566).

When a sprint is PATCHed to status=completed, the system should:
1. Create no "tests needed" alert rows (DWB-463 removed them); the close is
   represented in the feed by the sprint_closed event alone.
2. Mint a test ticket onto THE CLOSING SPRINT with status backlog and no
   assignee (DWB-566). It does not search for another sprint, it does not
   depend on a tester being on the roster, and it never assigns an inactive
   agent.
"""

import pytest


@pytest.fixture
def sprint_close_project(client, make_project, make_epic):
    """Set up a project with agents assigned in the required roles."""
    # Sprint-close tests disable every default-True gate explicitly, so a
    # future gate flipped on by default fails the *gate's* own tests rather
    # than every test in this file.
    project = make_project(
        force_handoff_md=False,
        force_initial_md=False,
        force_architecture_md=False,
        force_coding_standards_md=False,
        force_test_run=False,
        force_test_coverage=False,
        force_standards_audit=False,
        force_consolidation=False,
        force_headers=False,
    )
    epic = make_epic(project_id=project["id"])

    agents = {}
    for role in ("team-lead", "pm", "tester"):
        agent = client.post("/api/agents", json={
            "project_id": project["id"],
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
    def test_closing_sprint_creates_no_tests_needed_alerts(self, client, sprint_close_project):
        # DWB-463: the per-role "tests needed" alert rows are removed. The close
        # itself is already represented in the feed by the sprint_closed event
        # (DWB-410), so no new feed entry is added here either.
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

        # No new alert rows for the tests-needed notice.
        alerts_after = client.get("/api/alerts", params={
            "project_id": ctx["project"]["id"],
        }).json()
        new_alerts = [
            a for a in alerts_after
            if a["id"] not in {al["id"] for al in alerts_before}
        ]
        assert all("tests needed" not in a["title"].lower() for a in new_alerts)

        # The close is represented in the feed by the existing sprint_closed event.
        feed = client.get(f"/api/projects/{ctx['project']['id']}/activity-feed").json()
        closed = [e for e in feed if e.get("action") == "sprint_closed"]
        assert len(closed) >= 1
        # And no duplicate tests_requested verb is emitted.
        assert not any(e.get("action") == "tests_requested" for e in feed)

    def test_sprint_closed_feed_event_present_on_close(self, client, sprint_close_project):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 5,
            "status": "active",
            "name": "Auth Rework",
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        feed = client.get(f"/api/projects/{ctx['project']['id']}/activity-feed").json()
        closed = [
            e for e in feed
            if e.get("action") == "sprint_closed" and e.get("entity_id") == sprint["id"]
        ]
        assert len(closed) == 1
        assert closed[0]["details"]["sprint_number"] == 5

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


def _minted_tickets(client, sprint_id):
    """The test tickets auto-minted onto a sprint by the close handler."""
    tickets = client.get("/api/tickets", params={"sprint_id": sprint_id}).json()
    return [t for t in tickets if t["title"].startswith("Write tests for S")]


class TestSprintCloseAutoTicket:
    """DWB-566: the mint lands on the closing sprint, as backlog, unassigned."""

    def test_mint_lands_on_closing_sprint_with_no_other_sprint(
        self, client, sprint_close_project
    ):
        """The normal case, never covered before DWB-566.

        A sprint is created at the start of the session that works it, so at
        close time there is no other sprint on the project at all. The old
        next-sprint search minted nothing here (or, on a project carrying a
        stale placeholder, minted onto that placeholder).
        """
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
            "name": "Feature Sprint",
        }).json()

        # No other sprint exists on this project.
        all_sprints = client.get("/api/sprints", params={
            "project_id": ctx["project"]["id"],
        }).json()
        assert len(all_sprints) == 1

        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200

        minted = _minted_tickets(client, sprint["id"])
        assert len(minted) == 1
        tt = minted[0]
        assert tt["sprint_id"] == sprint["id"]
        assert tt["status"] == "backlog"
        assert tt["assigned_agent_id"] is None
        assert tt["ticket_type"] == "task"
        assert tt["epic_id"] == ctx["epic"]["id"]
        assert tt["title"] == "Write tests for S1: Feature Sprint"

    def test_mint_ignores_another_planned_sprint(self, client, sprint_close_project):
        """A planned sprint is no longer a mint target: the closing sprint is."""
        ctx = sprint_close_project
        s1 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        # DWB-331: only one sprint per project can be active, so a queued
        # sprint sits at planned. Pre-DWB-566 this is where the mint landed.
        s2 = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 2,
            "status": "planned",
        }).json()

        client.patch(f"/api/sprints/{s1['id']}", json={"status": "completed"})

        assert len(_minted_tickets(client, s1["id"])) == 1
        assert _minted_tickets(client, s2["id"]) == []

    def test_mint_ignores_a_lower_numbered_stale_placeholder_sprint(
        self, client, sprint_close_project
    ):
        """The exact production shape that stranded ten tickets.

        A long-lived placeholder sprint sits at status=planned with a LOWER
        sprint_number than the sprint being closed. The old lookup ordered by
        sprint_number ASC, so the placeholder won every time.
        """
        ctx = sprint_close_project
        placeholder = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 14,
            "status": "planned",
            "name": "Backlog Placeholder",
        }).json()
        current = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 81,
            "status": "active",
            "name": "Current Work",
        }).json()

        client.patch(f"/api/sprints/{current['id']}", json={"status": "completed"})

        assert _minted_tickets(client, placeholder["id"]) == []
        minted = _minted_tickets(client, current["id"])
        assert len(minted) == 1
        assert minted[0]["title"] == "Write tests for S81: Current Work"

    def test_mint_never_assigns_an_inactive_tester(self, client, make_project, make_epic):
        """The only role-matching candidate being inactive yields no assignment.

        Pre-DWB-566 the lookup had no is_active filter, so a deactivated tester
        collected every minted ticket.
        """
        project = make_project(force_handoff_md=False)
        epic = make_epic(project_id=project["id"])

        inactive_tester = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": f"Retired Tester {project['id']}",
            "role": "tester",
            "api_key": f"inactive-tester-{project['id']}",
            "is_active": False,
        }).json()
        assert inactive_tester["is_active"] is False
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": inactive_tester["id"],
        })

        sprint = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 1, "status": "active",
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        minted = _minted_tickets(client, sprint["id"])
        assert len(minted) == 1
        assert minted[0]["assigned_agent_id"] is None
        assert minted[0]["assigned_agent_id"] != inactive_tester["id"]

    def test_mint_is_deterministic_with_two_active_testers(
        self, client, make_project, make_epic
    ):
        """Two active candidates cannot make the outcome depend on query plan.

        Pre-DWB-566 the lookup had no ORDER BY, so with two matching testers
        the assignee was whichever row the planner returned first. Closing
        twice over two projects with identical rosters must give the same
        answer both times, and that answer is "unassigned".
        """
        minted_assignees = []
        for run in range(2):
            project = make_project(force_handoff_md=False)
            epic = make_epic(project_id=project["id"])
            for n in (1, 2):
                agent = client.post("/api/agents", json={
                    "project_id": project["id"],
                    "name": f"Tester {n} P{project['id']}",
                    "role": "tester",
                    "api_key": f"dup-tester-{n}-{project['id']}",
                }).json()
                assert agent["is_active"] is True
                client.post("/api/project-agents", json={
                    "project_id": project["id"], "agent_id": agent["id"],
                })

            sprint = client.post("/api/sprints", json={
                "project_id": project["id"], "epic_id": epic["id"],
                "sprint_number": 1, "status": "active",
            }).json()
            client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

            minted = _minted_tickets(client, sprint["id"])
            assert len(minted) == 1, f"run {run} minted {len(minted)} tickets"
            minted_assignees.append(minted[0]["assigned_agent_id"])

        assert minted_assignees == [None, None]

    def test_mint_happens_with_no_tester_on_the_roster(
        self, client, make_project, make_epic
    ):
        """The mint does not depend on a tester existing.

        Pre-DWB-566 a missing tester suppressed the ticket entirely, so a
        project with no tester silently lost its test coverage reminder.
        """
        project = make_project(force_handoff_md=False)
        epic = make_epic(project_id=project["id"])

        agent = client.post("/api/agents", json={
            "project_id": project["id"],
            "name": f"TL Only {project['id']}", "role": "team-lead",
            "api_key": f"tl-only-{project['id']}",
        }).json()
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": agent["id"],
        })

        sprint = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 7, "status": "active", "name": "No Tester Sprint",
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        minted = _minted_tickets(client, sprint["id"])
        assert len(minted) == 1
        assert minted[0]["assigned_agent_id"] is None
        assert minted[0]["status"] == "backlog"

    def test_mint_happens_with_no_agents_at_all(self, client, make_project, make_epic):
        project = make_project(force_handoff_md=False)
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 1, "status": "active",
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        assert len(_minted_tickets(client, sprint["id"])) == 1

    def test_minted_ticket_key_uses_project_prefix_and_next_number(
        self, client, sprint_close_project
    ):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()
        existing = client.post("/api/tickets", json={
            "project_id": ctx["project"]["id"],
            "sprint_id": sprint["id"],
            "epic_id": ctx["epic"]["id"],
            "ticket_number": 41,
            "ticket_key": f"{ctx['project']['prefix']}-041",
            "title": "Some earlier work",
        }).json()
        assert existing["ticket_number"] == 41

        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})

        minted = _minted_tickets(client, sprint["id"])
        assert len(minted) == 1
        assert minted[0]["ticket_key"] == f"{ctx['project']['prefix']}-042"
        # DWB-529: ticket_number and ticket_key must agree.
        assert minted[0]["ticket_number"] == 42

    def test_closing_already_completed_sprint_no_duplicate(
        self, client, sprint_close_project
    ):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 1,
            "status": "active",
        }).json()

        # Close once
        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        after_first = _minted_tickets(client, sprint["id"])
        assert len(after_first) == 1

        # Close again (already completed -> completed, should be a no-op)
        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        after_second = _minted_tickets(client, sprint["id"])

        assert len(after_second) == 1
        assert after_second[0]["id"] == after_first[0]["id"]

    def test_non_completed_transition_mints_nothing(self, client, sprint_close_project):
        ctx = sprint_close_project
        sprint = client.post("/api/sprints", json={
            "project_id": ctx["project"]["id"],
            "epic_id": ctx["epic"]["id"],
            "sprint_number": 2,
            "status": "active",
        }).json()

        client.patch(f"/api/sprints/{sprint['id']}", json={"goal": "Ship the thing"})

        assert _minted_tickets(client, sprint["id"]) == []
