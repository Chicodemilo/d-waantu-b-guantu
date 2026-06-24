# Path:          tests/test_tickets.py
# File:          test_tickets.py
# Created:       2026-03-28
# Purpose:       Full CRUD + filtering tests for /api/tickets
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/tickets, POST /api/tickets/:id/tokens
# Data In:       Factory-created projects, sprints, agents via conftest fixtures
# Data Out:      Assertions on HTTP status codes, JSON shapes, and token increments
# Last Modified: 2026-06-12

"""Tests for /api/tickets CRUD and filtering."""

import pytest


class TestListTickets:
    def test_list_returns_200(self, client):
        r = client.get("/api/tickets")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_filter_by_project_id(self, client, make_project, make_ticket):
        p1 = make_project()
        p2 = make_project()
        t1 = make_ticket(project_id=p1["id"])
        t2 = make_ticket(project_id=p2["id"])

        filtered = client.get("/api/tickets", params={"project_id": p1["id"]}).json()
        ids = [t["id"] for t in filtered]
        assert t1["id"] in ids
        assert t2["id"] not in ids

    def test_filter_by_status(self, client, make_ticket):
        make_ticket(status="todo")
        make_ticket(status="in_progress")

        todo = client.get("/api/tickets", params={"status": "todo"}).json()
        assert all(t["status"] == "todo" for t in todo)

    def test_filter_by_ticket_type(self, client, make_ticket):
        make_ticket(ticket_type="bug")
        make_ticket(ticket_type="story")

        bugs = client.get("/api/tickets", params={"ticket_type": "bug"}).json()
        assert all(t["ticket_type"] == "bug" for t in bugs)


class TestGetTicket:
    def test_get_returns_200(self, client, make_ticket):
        ticket = make_ticket()
        r = client.get(f"/api/tickets/{ticket['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == ticket["id"]

    def test_get_response_shape(self, client, make_ticket):
        ticket = make_ticket()
        data = client.get(f"/api/tickets/{ticket['id']}").json()
        expected_keys = {
            "id", "project_id", "epic_id", "sprint_id", "assigned_agent_id",
            "ticket_number", "ticket_key", "title", "description",
            "ticket_type", "status", "tokens_used", "time_spent_seconds",
            "token_source", "jira_issue_key",
            "parent_ticket_id", "subtasks",
            "created_at", "updated_at", "completed_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/tickets/999999")
        assert r.status_code == 404


class TestCreateTicket:
    def test_create_returns_201(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = client.post("/api/tickets", json={
            "project_id": project["id"],
            "ticket_number": 1,
            "ticket_key": "CRT-001",
            "title": "Created ticket",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "Created ticket"
        assert data["status"] == "backlog"  # default
        assert data["ticket_type"] == "task"  # default

    def test_create_with_all_fields(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = client.post("/api/tickets", json={
            "project_id": project["id"],
            "ticket_number": 2,
            "ticket_key": "CRT-002",
            "title": "Full ticket",
            "description": "Detailed desc",
            "ticket_type": "bug",
            "status": "todo",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["ticket_type"] == "bug"
        assert data["status"] == "todo"
        assert data["description"] == "Detailed desc"


class TestUpdateTicket:
    def test_patch_updates_fields(self, client, make_ticket):
        ticket = make_ticket()
        r = client.patch(f"/api/tickets/{ticket['id']}", json={
            "title": "Updated Title",
            "status": "in_progress",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Title"
        assert r.json()["status"] == "in_progress"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/tickets/999999", json={"title": "Nope"})
        assert r.status_code == 404


class TestCompletedAtStamp:
    """DWB-373: PATCH-to-done stamps Ticket.completed_at so the sessions list
    aggregator can count completions in window. Re-stamps on rework→done so
    the later closing session wins attribution. Preserved across rework-out
    (out of done) so the historical timestamp remains until next close."""

    def test_patch_to_done_stamps_completed_at(self, client, make_ticket):
        ticket = make_ticket(status="in_progress")
        assert ticket["completed_at"] is None

        r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        assert r.status_code == 200
        assert r.json()["completed_at"] is not None

    def test_non_done_transitions_do_not_stamp(self, client, make_ticket):
        ticket = make_ticket(status="todo")
        r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        assert r.status_code == 200
        assert r.json()["completed_at"] is None

    def test_rework_out_of_done_preserves_completed_at(self, client, make_ticket):
        ticket = make_ticket(status="in_progress")
        done = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"}).json()
        first_stamp = done["completed_at"]
        assert first_stamp is not None

        reworked = client.patch(
            f"/api/tickets/{ticket['id']}", json={"status": "in_progress"}
        ).json()
        assert reworked["completed_at"] == first_stamp

    def test_redone_after_rework_restamps_completed_at(self, client, make_ticket):
        ticket = make_ticket(status="in_progress")
        first = client.patch(
            f"/api/tickets/{ticket['id']}", json={"status": "done"}
        ).json()["completed_at"]
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        # Force a deterministic gap so the new timestamp can't tie the old.
        import time
        time.sleep(1.05)

        second = client.patch(
            f"/api/tickets/{ticket['id']}", json={"status": "done"}
        ).json()["completed_at"]
        assert second != first
        assert second > first

    def test_patch_idempotent_done_status_does_not_restamp(self, client, make_ticket):
        ticket = make_ticket(status="done")
        # Stamp it via a leaving-and-returning round trip to seed completed_at,
        # since make_ticket("done") goes through the create path which does not
        # stamp (intentional: only PATCH transitions count).
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        first = client.patch(
            f"/api/tickets/{ticket['id']}", json={"status": "done"}
        ).json()["completed_at"]
        assert first is not None

        # PATCH with status=done again (no actual transition) should NOT
        # restamp; status_changed is False on a no-op.
        second = client.patch(
            f"/api/tickets/{ticket['id']}", json={"status": "done"}
        ).json()["completed_at"]
        assert second == first


class TestDeleteTicket:
    def test_delete_returns_204(self, client, make_ticket):
        ticket = make_ticket()
        r = client.delete(f"/api/tickets/{ticket['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_ticket):
        ticket = make_ticket()
        client.delete(f"/api/tickets/{ticket['id']}")
        r = client.get(f"/api/tickets/{ticket['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/tickets/999999")
        assert r.status_code == 404


class TestStaleCheckDedup:
    """DWB-388 — POST /api/tickets/stale-check dedup key.

    Frontend sweeper (LiveSessions.jsx) buckets elapsed minutes into 10/20/30…
    thresholds and POSTs each new threshold every 10 min. Previous dedup
    matched on title.contains(f"{minutes_stale}m") so every threshold hop
    bypassed dedup and created a new row (13 dupes for RVP-007). New dedup is
    (ticket_id, "stale" in title, status in {open, acknowledged}).
    """

    def _make_pm(self, client, project_id, make_agent):
        # stale_check needs a PM on the project to attribute the raiser_id.
        pm = make_agent(
            project_id=project_id, name="StalePM", role="pm",
            api_key=f"stale-pm-{project_id}",
        )
        client.post("/api/project-agents", json={
            "project_id": project_id, "agent_id": pm["id"],
        })
        return pm

    def test_first_call_creates_alert(self, client, make_project, make_ticket, make_agent):
        project = make_project()
        self._make_pm(client, project["id"], make_agent)
        ticket = make_ticket(project_id=project["id"], status="in_progress")

        r = client.post("/api/tickets/stale-check", json={
            "ticket_id": ticket["id"], "project_id": project["id"],
            "minutes_stale": 10, "agent_name": "Tester",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["alert_created"] is True
        assert body["alert_id"] is not None

    def test_second_call_same_threshold_is_deduped(self, client, make_project, make_ticket, make_agent):
        project = make_project()
        self._make_pm(client, project["id"], make_agent)
        ticket = make_ticket(project_id=project["id"], status="in_progress")

        payload = {
            "ticket_id": ticket["id"], "project_id": project["id"],
            "minutes_stale": 10, "agent_name": "Tester",
        }
        first = client.post("/api/tickets/stale-check", json=payload).json()
        second = client.post("/api/tickets/stale-check", json=payload).json()
        assert first["alert_created"] is True
        assert second["alert_created"] is False

    def test_higher_thresholds_dedup_against_earlier_alert(self, client, make_project, make_ticket, make_agent):
        """The 13-dupes-for-RVP-007 regression: threshold hops must NOT bypass dedup."""
        project = make_project()
        self._make_pm(client, project["id"], make_agent)
        ticket = make_ticket(project_id=project["id"], status="in_progress")

        first = client.post("/api/tickets/stale-check", json={
            "ticket_id": ticket["id"], "project_id": project["id"],
            "minutes_stale": 10, "agent_name": "Tester",
        }).json()
        assert first["alert_created"] is True

        # The LiveSessions sweeper bumps the threshold every 10 min. Each of
        # these used to create a fresh alert because the title substring
        # f"{minutes_stale}m" was part of the dedup key.
        for minutes in (20, 30, 60, 130):
            r = client.post("/api/tickets/stale-check", json={
                "ticket_id": ticket["id"], "project_id": project["id"],
                "minutes_stale": minutes, "agent_name": "Tester",
            }).json()
            assert r["alert_created"] is False, (
                f"threshold hop to {minutes}m should not bypass dedup"
            )

        # Exactly one open alert exists for this ticket.
        alerts = client.get("/api/alerts", params={"project_id": project["id"]}).json()
        stale_alerts = [
            a for a in alerts
            if a["ticket_id"] == ticket["id"] and "stale" in a["title"]
        ]
        assert len(stale_alerts) == 1

    def test_dedup_isolated_per_ticket(self, client, make_project, make_ticket, make_agent):
        """Dedup must not leak across tickets — each stuck ticket gets its own alert."""
        project = make_project()
        self._make_pm(client, project["id"], make_agent)
        t1 = make_ticket(project_id=project["id"], status="in_progress")
        t2 = make_ticket(project_id=project["id"], status="in_progress")

        r1 = client.post("/api/tickets/stale-check", json={
            "ticket_id": t1["id"], "project_id": project["id"],
            "minutes_stale": 10, "agent_name": "Tester",
        }).json()
        r2 = client.post("/api/tickets/stale-check", json={
            "ticket_id": t2["id"], "project_id": project["id"],
            "minutes_stale": 10, "agent_name": "Tester",
        }).json()
        assert r1["alert_created"] is True
        assert r2["alert_created"] is True
        assert r1["alert_id"] != r2["alert_id"]

    def test_rework_alert_does_not_block_stale_alert(self, client, db_session, make_project, make_ticket, make_agent):
        """Non-stale alerts tied to the same ticket must not be falsely deduped against.

        Rework alerts (created on in_progress->done->in_progress transitions)
        share ticket_id with stale alerts but have a different topic. The new
        dedup uses "stale" in title as the type discriminator so the two
        alert classes coexist cleanly.
        """
        from app.models.alert import Alert, AlertSeverity, AlertStatus

        project = make_project()
        pm = self._make_pm(client, project["id"], make_agent)
        ticket = make_ticket(project_id=project["id"], status="in_progress")

        # Hand-roll a rework-style alert on the same ticket. Don't go through
        # the auto-rework path (which requires a full done->in_progress flow);
        # we only need an alert row with the right shape for dedup to see.
        db_session.add(Alert(
            project_id=project["id"],
            raised_by_agent_id=pm["id"],
            ticket_id=ticket["id"],
            title=f"Rework detected: {ticket['ticket_key']}",
            body="precondition for dedup test",
            severity=AlertSeverity.info,
            status=AlertStatus.open,
        ))
        db_session.commit()

        r = client.post("/api/tickets/stale-check", json={
            "ticket_id": ticket["id"], "project_id": project["id"],
            "minutes_stale": 10, "agent_name": "Tester",
        }).json()
        assert r["alert_created"] is True, (
            "stale alert must still be created when only a rework alert exists"
        )
