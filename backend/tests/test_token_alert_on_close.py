# Path: tests/test_token_alert_on_close.py
# File: test_token_alert_on_close.py
# Created: 2026-03-28
# Purpose: Tests that the tokens-not-reported alert is NOT created on ticket close (DWB-353 removed the fire path)
# Caller: pytest
# Callees: PATCH /api/tickets, POST /api/tickets/:id/tokens, GET /api/alerts
# Data In: Factory-created tickets, agents via conftest fixtures
# Data Out: Assertions that no "Tokens not reported" alert exists post-close
# Last Modified: 2026-06-10

"""DWB-353: the tokens-not-reported alert is removed.

The pre-hook workflow had agents POST to /api/tickets/:id/tokens at
session end and the alert fired when they forgot. The hook attribution
layer (SessionStart / SubagentStop -> hook_sessions -> tracking_log ->
by_ticket rollup) made ticket.tokens_used dead for hook-attributed
work, so the alert fired on every close and was pure noise.

These tests pin the negative: closing a ticket - with or without tokens
reported, with or without an assigned agent - does not produce any
"Tokens not reported" alert. The spec asserts the file should keep its
test ID surface so the failure mode is obvious if a future change
resurrects the alert; the assertions are flipped accordingly.
"""


def _tokens_not_reported_alerts(client, project_id, ticket_id):
    """Return any alerts matching the dead 'Tokens not reported' title for
    a given ticket. The shape we used to assert ON should now always be
    empty after a close."""
    alerts = client.get("/api/alerts", params={"project_id": project_id}).json()
    return [
        a for a in alerts
        if a.get("ticket_id") == ticket_id
        and "Tokens not reported" in a.get("title", "")
    ]


class TestTokenAlertRemoved:
    """DWB-353: every close path must produce zero tokens-not-reported alerts."""

    def test_closing_with_zero_tokens_does_not_create_alert(
        self, client, make_ticket, make_agent,
    ):
        """The headline regression test: closing a ticket with
        tokens_used=0 used to auto-create an info alert. DWB-353 removed
        the fire path entirely. No alert should appear."""
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        assert ticket["tokens_used"] == 0

        r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        assert r.status_code == 200

        matching = _tokens_not_reported_alerts(
            client, ticket["project_id"], ticket["id"],
        )
        assert matching == []

    def test_closing_with_tokens_does_not_create_alert(
        self, client, make_ticket, make_agent,
    ):
        """Symmetric case: closing with tokens reported also produces no
        alert. (Always true; pinned to catch any regression that wires a
        different alert title that still mentions 'Tokens not reported'.)"""
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])

        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 500, "time_spent_seconds": 30,
        })
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        matching = _tokens_not_reported_alerts(
            client, ticket["project_id"], ticket["id"],
        )
        assert matching == []

    def test_no_alert_when_no_assigned_agent(self, client, make_ticket):
        """The legacy fire path also guarded on assigned_agent_id; the
        guard is irrelevant now since the whole fire path is gone, but
        keep the test for symmetry."""
        ticket = make_ticket()
        assert ticket["assigned_agent_id"] is None

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        matching = _tokens_not_reported_alerts(
            client, ticket["project_id"], ticket["id"],
        )
        assert matching == []

    def test_non_done_status_does_not_create_alert(
        self, client, make_ticket, make_agent,
    ):
        """Non-done transitions never fired the alert. Stays true."""
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        matching = _tokens_not_reported_alerts(
            client, ticket["project_id"], ticket["id"],
        )
        assert matching == []
