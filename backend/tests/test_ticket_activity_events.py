# Path:          tests/test_ticket_activity_events.py
# File:          test_ticket_activity_events.py
# Created:       2026-06-19
# Purpose:       Tests for semantic ticket activity events emitted via log_activity (DWB-409)
# Caller:        pytest
# Callees:       PATCH /api/tickets/{id}, app.models.activity_log.ActivityLog
# Data In:       Factory-created project/agent/ticket, in-process db_session
# Data Out:      Assertions on status_changed / assigned / reopened activity_log rows
# Last Modified: 2026-06-19 (DWB-409)

"""Semantic ticket-event tests: status_changed, assigned, reopened."""

import json

from sqlalchemy import select

from app.models.activity_log import ActivityLog


def _events(db_session, ticket_id, action=None):
    """Semantic activity_log rows for a ticket (visible in the request session)."""
    stmt = select(ActivityLog).where(
        ActivityLog.entity_type == "ticket",
        ActivityLog.entity_id == ticket_id,
    )
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    return list(db_session.scalars(stmt).all())


def _details(row):
    return json.loads(row.details) if row.details else None


class TestStatusChangedEvent:
    def test_status_transition_emits_status_changed(self, client, db_session, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent(project_id=ticket["project_id"])
        r = client.patch(
            f"/api/tickets/{ticket['id']}",
            json={"status": "in_progress"},
            headers={"X-Agent-ID": str(agent["id"])},
        )
        assert r.status_code == 200

        rows = _events(db_session, ticket["id"], "status_changed")
        assert len(rows) == 1
        assert _details(rows[0]) == {"from": ticket["status"], "to": "in_progress"}
        assert rows[0].agent_id == agent["id"]
        assert rows[0].project_id == ticket["project_id"]

    def test_no_status_changed_when_status_unchanged(self, client, db_session, make_ticket):
        ticket = make_ticket()
        # PATCH a non-status field; status stays the same.
        r = client.patch(f"/api/tickets/{ticket['id']}", json={"title": "Renamed"})
        assert r.status_code == 200
        assert _events(db_session, ticket["id"], "status_changed") == []

    def test_actor_falls_back_to_assignee_without_header(self, client, db_session, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        # No X-Agent-ID header -> actor falls back to the current assignee.
        r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        assert r.status_code == 200
        rows = _events(db_session, ticket["id"], "status_changed")
        assert len(rows) == 1
        assert rows[0].agent_id == agent["id"]


class TestAssignedEvent:
    def test_assignment_emits_assigned(self, client, db_session, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent(project_id=ticket["project_id"], name="Assignee One")
        r = client.patch(
            f"/api/tickets/{ticket['id']}",
            json={"assigned_agent_id": agent["id"]},
        )
        assert r.status_code == 200
        rows = _events(db_session, ticket["id"], "assigned")
        assert len(rows) == 1
        assert _details(rows[0]) == {"agent": "Assignee One", "agent_id": agent["id"]}

    def test_no_assigned_when_unchanged(self, client, db_session, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        # Re-PATCH the same assignee: no new assigned event.
        r = client.patch(
            f"/api/tickets/{ticket['id']}",
            json={"assigned_agent_id": agent["id"]},
        )
        assert r.status_code == 200
        assert _events(db_session, ticket["id"], "assigned") == []

    def test_no_assigned_when_set_to_null(self, client, db_session, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        r = client.patch(
            f"/api/tickets/{ticket['id']}",
            json={"assigned_agent_id": None},
        )
        assert r.status_code == 200
        # Unassigning is not an "assigned" event.
        assert _events(db_session, ticket["id"], "assigned") == []


class TestReopenedEvent:
    def test_done_to_in_progress_emits_reopened_only(self, client, db_session, make_ticket, make_agent):
        # DWB-409 TL decision: reopened REPLACES status_changed for the
        # done->in_progress transition (one semantic row per event).
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        tid = ticket["id"]
        client.patch(f"/api/tickets/{tid}", json={"status": "done"})
        r = client.patch(f"/api/tickets/{tid}", json={"status": "in_progress"})
        assert r.status_code == 200

        reopened = _events(db_session, tid, "reopened")
        assert len(reopened) == 1
        assert _details(reopened[0]) == {"from": "done", "to": "in_progress"}

        # NO status_changed row for the done->in_progress transition (reopened
        # took its place). Earlier transitions (e.g. ->done) keep their own.
        sc_reopen = [r for r in _events(db_session, tid, "status_changed")
                     if _details(r) == {"from": "done", "to": "in_progress"}]
        assert sc_reopen == []

    def test_normal_transition_does_not_emit_reopened(self, client, db_session, make_ticket):
        ticket = make_ticket()
        r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        assert r.status_code == 200
        assert _events(db_session, ticket["id"], "reopened") == []

    def test_in_review_to_in_progress_not_reopened(self, client, db_session, make_ticket):
        # Only a done -> in_progress transition counts as a reopen.
        ticket = make_ticket()
        tid = ticket["id"]
        client.patch(f"/api/tickets/{tid}", json={"status": "in_progress"})
        client.patch(f"/api/tickets/{tid}", json={"status": "in_review"})
        client.patch(f"/api/tickets/{tid}", json={"status": "in_progress"})
        assert _events(db_session, tid, "reopened") == []


class TestFeedDedup:
    """DWB-409 read-side dedup in GET /api/projects/{id}/activity-feed:
    suppress the generic middleware row when a semantic sibling exists for the
    same (entity_type, entity_id) within the dedup window.

    Rows are inserted directly because the middleware writes its generic row on
    a SEPARATE connection (its commit isn't visible to the test transaction),
    so a live PATCH can't reproduce both rows in one feed query. Direct inserts
    give controlled timestamps to exercise the window logic precisely.
    """

    def _add(self, db_session, pid, entity_id, action, created_at, details=None):
        from datetime import datetime as _dt
        row = ActivityLog(
            project_id=pid,
            agent_id=None,
            entity_type="ticket",
            entity_id=entity_id,
            action=action,
            details=json.dumps(details) if details else None,
            created_at=created_at,
        )
        db_session.add(row)
        db_session.flush()
        return row

    def test_generic_suppressed_when_semantic_sibling_in_window(self, client, db_session, make_project):
        from datetime import datetime
        project = make_project()
        pid = project["id"]
        t = datetime(2026, 6, 19, 12, 0, 0)
        self._add(db_session, pid, 500, "updated", t, {"status": "in_progress"})
        self._add(db_session, pid, 500, "status_changed", t, {"from": "todo", "to": "in_progress"})
        db_session.commit()

        feed = client.get(f"/api/projects/{pid}/activity-feed?limit=200").json()
        rows = [r for r in feed if r["entity_id"] == 500]
        assert [r["action"] for r in rows] == ["status_changed"]  # updated suppressed

    def test_lone_generic_row_is_kept(self, client, db_session, make_project):
        from datetime import datetime
        project = make_project()
        pid = project["id"]
        self._add(db_session, pid, 501, "created", datetime(2026, 6, 19, 12, 0, 0))
        db_session.commit()

        feed = client.get(f"/api/projects/{pid}/activity-feed?limit=200").json()
        rows = [r for r in feed if r["entity_id"] == 501]
        assert [r["action"] for r in rows] == ["created"]  # no sibling -> kept

    def test_generic_kept_when_semantic_outside_window(self, client, db_session, make_project):
        from datetime import datetime
        project = make_project()
        pid = project["id"]
        # 60s apart -> outside the 5s dedup window -> both surface.
        self._add(db_session, pid, 502, "updated", datetime(2026, 6, 19, 12, 0, 0))
        self._add(db_session, pid, 502, "status_changed", datetime(2026, 6, 19, 12, 1, 0),
                  {"from": "todo", "to": "done"})
        db_session.commit()

        feed = client.get(f"/api/projects/{pid}/activity-feed?limit=200").json()
        actions = sorted(r["action"] for r in feed if r["entity_id"] == 502)
        assert actions == ["status_changed", "updated"]

    def test_created_not_shadowed_by_status_changed_in_window(self, client, db_session, make_project):
        # Action-class pairing: a `created` row is NOT shadowed by
        # `status_changed` (which only shadows `updated`), so a ticket created
        # and transitioned within the window keeps BOTH rows. Regression for
        # the bug where a bare time window wrongly hid the creation row.
        from datetime import datetime
        project = make_project()
        pid = project["id"]
        t = datetime(2026, 6, 19, 12, 0, 0)
        self._add(db_session, pid, 503, "created", t)               # creation
        self._add(db_session, pid, 503, "updated", t)               # the PATCH's generic shadow
        self._add(db_session, pid, 503, "status_changed", t, {"from": "todo", "to": "in_progress"})
        db_session.commit()

        feed = client.get(f"/api/projects/{pid}/activity-feed?limit=200").json()
        actions = sorted(r["action"] for r in feed if r["entity_id"] == 503)
        # `updated` suppressed (shadowed by status_changed); `created` survives.
        assert actions == ["created", "status_changed"]
