# Path:          tests/test_status_history.py
# File:          test_status_history.py
# Created:       2026-03-28
# Purpose:       Tests for status history tracking, rework detection, and time computation
# Caller:        pytest
# Callees:       PATCH /api/tickets, GET /api/tickets/:id/history, GET /api/failure-records
# Data In:       Factory-created tickets, agents, projects via conftest fixtures
# Data Out:      Assertions on history records, failure records, and time_spent_seconds
# Last Modified: 2026-03-29

"""Tests for status history, rework detection, and time computation (Sprint 27)."""

import time

import pytest


@pytest.fixture
def project_with_pm(client, make_project, make_agent):
    """Create a project with a PM agent assigned."""
    project = make_project()
    pm = client.post("/api/agents", json={
        "name": "PM Agent",
        "role": "pm",
        "api_key": f"pm-key-{project['id']}",
    }).json()
    client.post("/api/project-agents", json={
        "project_id": project["id"],
        "agent_id": pm["id"],
    })
    return {"project": project, "pm": pm}


class TestStatusHistory:
    def test_status_change_creates_history_record(self, client, make_ticket):
        ticket = make_ticket()
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        history = client.get(f"/api/tickets/{ticket['id']}/history").json()
        assert len(history) >= 1
        entry = history[-1]
        assert entry["old_status"] == "backlog"
        assert entry["new_status"] == "in_progress"
        assert entry["ticket_id"] == ticket["id"]

    def test_multiple_transitions_recorded_in_order(self, client, make_ticket):
        ticket = make_ticket()
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        history = client.get(f"/api/tickets/{ticket['id']}/history").json()
        assert len(history) >= 2
        assert history[0]["new_status"] == "in_progress"
        assert history[1]["old_status"] == "in_progress"
        assert history[1]["new_status"] == "done"

    def test_history_response_shape(self, client, make_ticket):
        ticket = make_ticket()
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        history = client.get(f"/api/tickets/{ticket['id']}/history").json()
        expected_keys = {
            "id", "ticket_id", "old_status", "new_status",
            "changed_at", "changed_by_agent_id",
        }
        assert set(history[0].keys()) == expected_keys

    def test_no_history_without_status_change(self, client, make_ticket):
        ticket = make_ticket()
        # Patch a non-status field
        client.patch(f"/api/tickets/{ticket['id']}", json={"title": "Updated"})

        history = client.get(f"/api/tickets/{ticket['id']}/history").json()
        assert len(history) == 0

    def test_same_status_no_duplicate_record(self, client, make_ticket):
        ticket = make_ticket()
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "backlog"})

        history = client.get(f"/api/tickets/{ticket['id']}/history").json()
        assert len(history) == 0

    def test_history_includes_agent_id(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        history = client.get(f"/api/tickets/{ticket['id']}/history").json()
        assert history[0]["changed_by_agent_id"] == agent["id"]

    def test_history_404_for_nonexistent_ticket(self, client):
        r = client.get("/api/tickets/999999/history")
        assert r.status_code == 404


class TestReworkDetection:
    def test_done_to_in_progress_creates_failure_record(
        self, client, make_ticket, make_agent, project_with_pm
    ):
        proj = project_with_pm
        agent = make_agent()
        ticket = make_ticket(
            project_id=proj["project"]["id"],
            assigned_agent_id=agent["id"],
        )

        # Move to done then back to in_progress
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        # Check failure record created with type="rework"
        records = client.get("/api/failure-records", params={
            "project_id": proj["project"]["id"],
            "failure_type": "rework",
        }).json()
        matching = [r for r in records if r["ticket_id"] == ticket["id"]]
        assert len(matching) >= 1
        assert matching[0]["failure_type"] == "rework"
        assert matching[0]["resolved"] is False

    def test_rework_creates_pm_alert(
        self, client, make_ticket, make_agent, project_with_pm
    ):
        proj = project_with_pm
        agent = make_agent()
        ticket = make_ticket(
            project_id=proj["project"]["id"],
            assigned_agent_id=agent["id"],
        )

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        # Check PM alert
        alerts = client.get("/api/alerts", params={
            "project_id": proj["project"]["id"],
        }).json()
        rework_alerts = [
            a for a in alerts
            if "Rework detected" in a.get("title", "")
            and a.get("ticket_id") == ticket["id"]
        ]
        assert len(rework_alerts) >= 1
        assert rework_alerts[0]["raised_by_agent_id"] == proj["pm"]["id"]

    def test_no_rework_without_prior_done(self, client, make_ticket, project_with_pm):
        proj = project_with_pm
        ticket = make_ticket(project_id=proj["project"]["id"])

        # backlog → in_progress (no prior done, no rework)
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        records = client.get("/api/failure-records", params={
            "project_id": proj["project"]["id"],
            "failure_type": "rework",
        }).json()
        matching = [r for r in records if r.get("ticket_id") == ticket["id"]]
        assert len(matching) == 0

    def test_no_rework_without_pm(self, client, make_ticket, make_agent):
        """No PM assigned — rework detection skips (no failure record or alert)."""
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        records = client.get("/api/failure-records", params={
            "failure_type": "rework",
        }).json()
        matching = [r for r in records if r.get("ticket_id") == ticket["id"]]
        assert len(matching) == 0

    def test_rework_failure_record_notes_mention_ticket_key(
        self, client, make_ticket, make_agent, project_with_pm
    ):
        proj = project_with_pm
        agent = make_agent()
        ticket = make_ticket(
            project_id=proj["project"]["id"],
            assigned_agent_id=agent["id"],
        )

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        records = client.get("/api/failure-records", params={
            "project_id": proj["project"]["id"],
            "failure_type": "rework",
        }).json()
        matching = [r for r in records if r["ticket_id"] == ticket["id"]]
        assert ticket["ticket_key"] in matching[0]["notes"]


class TestTimeComputation:
    def test_in_progress_to_done_computes_time(self, client, make_ticket):
        ticket = make_ticket()

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        # Small sleep so there's a nonzero delta between status_history timestamps
        time.sleep(1.1)
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        updated = client.get(f"/api/tickets/{ticket['id']}").json()
        assert updated["time_spent_seconds"] >= 1

    def test_ticket_never_in_progress_has_zero_time(self, client, make_ticket):
        ticket = make_ticket()

        # Skip in_progress, go straight to done
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        updated = client.get(f"/api/tickets/{ticket['id']}").json()
        assert updated["time_spent_seconds"] == 0

    def test_multiple_in_progress_windows(self, client, make_ticket):
        ticket = make_ticket()

        # First window
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        time.sleep(1.1)
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        t1 = client.get(f"/api/tickets/{ticket['id']}").json()["time_spent_seconds"]
        assert t1 >= 1

        # Second window (rework)
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        time.sleep(1.1)
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        t2 = client.get(f"/api/tickets/{ticket['id']}").json()["time_spent_seconds"]
        assert t2 >= 2  # accumulated from both windows
        assert t2 > t1

    def test_currently_in_progress_not_counted(self, client, make_ticket):
        """Open in_progress interval (no exit transition) is not counted."""
        ticket = make_ticket()

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        time.sleep(0.5)

        updated = client.get(f"/api/tickets/{ticket['id']}").json()
        assert updated["time_spent_seconds"] == 0
