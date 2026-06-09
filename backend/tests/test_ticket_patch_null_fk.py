# Path: tests/test_ticket_patch_null_fk.py
# File: test_ticket_patch_null_fk.py
# Created: 2026-06-09
# Purpose: Regression tests for PATCH /api/tickets/{id} null-FK handling (DWB-333)
# Caller: pytest
# Callees: app.routers.tickets, app.services.ticket
# Data In: per-test factory fixtures
# Data Out: Assertions on status codes + response bodies
# Last Modified: 2026-06-09

"""DWB-333 bug repro + fix verification.

Original bug (reported by Archie_CI on FRAUDI): PATCH `{"sprint_id": null}`
returned a generic 500 instead of a clean response. Root cause: the
TicketUpdate schema declared sprint_id as `int | None`, but the Ticket
model has sprint_id NOT NULL per the project hierarchy rule (every ticket
must belong to a sprint). Pydantic let the null through, the assignment
hit MySQL's NOT NULL, IntegrityError surfaced as 500.

Fix: service-layer reject of explicit null with a clean 400 + actionable
message telling the caller to reassign instead of detach.

Sibling FKs checked separately:
- epic_id IS nullable in the model — PATCH null is a valid detach, must 200.
- assigned_agent_id IS nullable — PATCH null also valid, must 200.
"""


class TestSprintIdNullRejection:
    """sprint_id=null must be a clean 400, not a 500."""

    def test_explicit_null_sprint_id_returns_400(self, client, make_ticket):
        t = make_ticket()
        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"sprint_id": None},
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", {})
        assert detail.get("error") == "sprint_id_required"
        assert detail.get("field") == "sprint_id"
        assert "reassign" in detail.get("message", "").lower()

    def test_mixed_payload_status_plus_null_sprint_is_400(
        self, client, make_ticket
    ):
        """A mixed payload {status: X, sprint_id: null} must reject and NOT
        partially apply the status change either — the null sprint_id is the
        rejection trigger, the rest of the body is moot."""
        t = make_ticket()
        original_status = t["status"]
        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"status": "backlog", "sprint_id": None},
        )
        assert r.status_code == 400, r.text

        # Status did NOT change — verify via GET.
        after = client.get(f"/api/tickets/{t['id']}").json()
        assert after["status"] == original_status
        assert after["sprint_id"] == t["sprint_id"]


class TestSprintIdReassignHappyPath:
    """Reassigning to a different sprint is the intended replacement workflow
    for what callers used to want from detach."""

    def test_reassign_to_different_sprint_succeeds(
        self, client, make_ticket, make_sprint
    ):
        t = make_ticket()
        new_sprint = make_sprint(project_id=t["project_id"])
        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"sprint_id": new_sprint["id"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["sprint_id"] == new_sprint["id"]

    def test_patch_without_sprint_id_field_passes_through(
        self, client, make_ticket
    ):
        """Omitting sprint_id from the body must not touch the field
        (exclude_unset semantics) — only an explicit null trips the new
        reject."""
        t = make_ticket()
        original_sprint_id = t["sprint_id"]
        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"status": "in_progress"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sprint_id"] == original_sprint_id
        assert body["status"] == "in_progress"


class TestSiblingNullableFKs:
    """epic_id and assigned_agent_id ARE nullable in the model, so null on
    them is a valid detach and must 200."""

    def test_epic_id_null_detaches_cleanly(self, client, make_ticket):
        t = make_ticket()
        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"epic_id": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["epic_id"] is None

    def test_assigned_agent_id_null_detaches_cleanly(
        self, client, make_ticket, make_agent
    ):
        t = make_ticket()
        # Give it an agent first so the null is a true clear.
        agent = make_agent(project_id=t["project_id"])
        client.patch(
            f"/api/tickets/{t['id']}",
            json={"assigned_agent_id": agent["id"]},
        )

        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"assigned_agent_id": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["assigned_agent_id"] is None

    def test_combined_null_epic_and_agent_succeeds(
        self, client, make_ticket, make_agent
    ):
        """Two nullable detaches in one payload — both apply, 200 response."""
        t = make_ticket()
        agent = make_agent(project_id=t["project_id"])
        client.patch(
            f"/api/tickets/{t['id']}",
            json={"assigned_agent_id": agent["id"]},
        )

        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"epic_id": None, "assigned_agent_id": None},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["epic_id"] is None
        assert body["assigned_agent_id"] is None
