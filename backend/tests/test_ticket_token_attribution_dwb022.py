# Path: tests/test_ticket_token_attribution_dwb022.py
# File: test_ticket_token_attribution_dwb022.py
# Created: 2026-08-12 (DWB-022)
# Purpose: DWB-022 - a ticket token increment MUST emit a matching tracking_log
#          token_report event and stamp a real token_source (never 'unknown'),
#          attributed to the acting/assigned agent; plus the historical reconcile
#          of pre-fix phantom rows.
# Caller: pytest
# Callees: POST /api/tickets/:id/tokens, app.services.tracking (reconcile,
#          compute_ticket_tokens), app.models (ticket, tracking_log)
# Data In: Factory-created project/agent/ticket via conftest fixtures
# Data Out: Assertions on TrackingLog rows + ticket.token_source
# Last Modified: 2026-08-12 (DWB-022)

from sqlalchemy import select

from app.models.ticket import Ticket
from app.models.tracking_log import TrackingLog
from app.services import tracking


def _token_events(db, ticket_id):
    return list(db.scalars(
        select(TrackingLog)
        .where(TrackingLog.ticket_id == ticket_id)
        .where(TrackingLog.event_type == "token_report")
    ).all())


class TestIncrementEmitsLedgerEvent:
    def test_token_increment_writes_matching_ledger_event(
        self, client, db_session, make_agent, make_ticket
    ):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        r = client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 500, "time_spent_seconds": 30,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        # Cache updated AND a real source stamped (never 'unknown').
        assert body["tokens_used"] == 500
        assert body["token_source"] not in (None, "unknown")
        assert body["token_source"] == "ticket_report"

        # A matching ledger event exists, attributed to the ticket's assignee,
        # so the ledger-derived rollup is no longer 0.
        events = _token_events(db_session, ticket["id"])
        assert len(events) == 1
        assert events[0].tokens == 500
        assert events[0].agent_id == agent["id"]
        assert events[0].source == "ticket_report"
        assert tracking.compute_ticket_tokens(db_session, ticket["id"]) == 500

    def test_explicit_source_is_honored(
        self, client, db_session, make_agent, make_ticket
    ):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 200, "time_spent_seconds": 10, "source": "manual",
        })
        events = _token_events(db_session, ticket["id"])
        assert len(events) == 1 and events[0].source == "manual"
        t = db_session.get(Ticket, ticket["id"])
        assert t.token_source == "manual"

    def test_x_agent_id_header_attributes_the_event(
        self, client, db_session, make_agent, make_ticket
    ):
        # Ticket unassigned; the X-Agent-ID caller is credited.
        caller = make_agent()
        ticket = make_ticket(project_id=caller["project_id"])
        r = client.post(
            f"/api/tickets/{ticket['id']}/tokens",
            json={"tokens_used": 300, "time_spent_seconds": 15},
            headers={"X-Agent-ID": str(caller["id"])},
        )
        assert r.status_code == 200, r.text
        events = _token_events(db_session, ticket["id"])
        assert len(events) == 1 and events[0].agent_id == caller["id"]

    def test_no_agent_no_assignee_is_rejected(self, client, make_ticket):
        # tokens > 0 with neither X-Agent-ID nor an assigned agent -> 400, never
        # a phantom write.
        ticket = make_ticket()  # unassigned
        r = client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 100, "time_spent_seconds": 5,
        })
        assert r.status_code == 400
        assert "attribute tokens" in r.json()["detail"].lower()

    def test_zero_token_report_writes_no_event(
        self, client, db_session, make_ticket
    ):
        # A time-only report (0 tokens) on an unassigned ticket must not 400 and
        # must not create a token event.
        ticket = make_ticket()
        r = client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 0, "time_spent_seconds": 45,
        })
        assert r.status_code == 200, r.text
        assert r.json()["time_spent_seconds"] == 45
        assert _token_events(db_session, ticket["id"]) == []


class TestReconcileOrphans:
    def _make_phantom(self, db, ticket_id, tokens=500):
        """Recreate a pre-DWB-022 phantom: tokens_used set + token_source
        'unknown' + NO tracking_log event (bypasses the fixed endpoint)."""
        t = db.get(Ticket, ticket_id)
        t.tokens_used = tokens
        t.token_source = "unknown"
        db.commit()

    def test_reconcile_backfills_ledger_and_fixes_source(
        self, db_session, make_agent, make_ticket
    ):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        self._make_phantom(db_session, ticket["id"], tokens=48000)
        assert _token_events(db_session, ticket["id"]) == []

        n = tracking.reconcile_orphan_ticket_tokens(db_session)
        assert n == 1

        events = _token_events(db_session, ticket["id"])
        assert len(events) == 1
        assert events[0].tokens == 48000
        assert events[0].agent_id == agent["id"]
        assert events[0].source == "reconciled"
        t = db_session.get(Ticket, ticket["id"])
        assert t.token_source == "reconciled"

    def test_reconcile_is_idempotent(
        self, db_session, make_agent, make_ticket
    ):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        self._make_phantom(db_session, ticket["id"])
        assert tracking.reconcile_orphan_ticket_tokens(db_session) == 1
        # Second run: nothing left to reconcile, no duplicate event.
        assert tracking.reconcile_orphan_ticket_tokens(db_session) == 0
        assert len(_token_events(db_session, ticket["id"])) == 1

    def test_reconcile_skips_ticket_without_assignee(
        self, db_session, make_ticket
    ):
        ticket = make_ticket()  # unassigned -> not attributable
        self._make_phantom(db_session, ticket["id"])
        assert tracking.reconcile_orphan_ticket_tokens(db_session) == 0
        assert _token_events(db_session, ticket["id"]) == []
        # Left untouched (still 'unknown'); can't fabricate an agent for it.
        t = db_session.get(Ticket, ticket["id"])
        assert t.token_source == "unknown"

    def test_reconcile_leaves_healthy_tickets_alone(
        self, client, db_session, make_agent, make_ticket
    ):
        # A ticket reported through the fixed endpoint already has its event and
        # a real source -> reconcile must not touch it or double-count.
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 700, "time_spent_seconds": 20,
        })
        assert tracking.reconcile_orphan_ticket_tokens(db_session) == 0
        assert len(_token_events(db_session, ticket["id"])) == 1
        assert tracking.compute_ticket_tokens(db_session, ticket["id"]) == 700
