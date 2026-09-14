# Path: tests/test_ticket_token_increment_dwb509.py
# File: test_ticket_token_increment_dwb509.py
# Created: 2026-09-14 (DWB-509)
# Purpose: DWB-509 - POST /api/tickets/:id/tokens must 422 on payload key
#          mismatch instead of silently binding tokens_used=0 and returning 200.
#          tokens_used is required, unknown keys are forbidden, and the success
#          response echoes the increment actually applied (so a zero-effect call
#          is visible).
# Caller: pytest
# Callees: POST /api/tickets/:id/tokens
# Data In: Factory-created project/agent/ticket via conftest fixtures
# Data Out: Assertions on HTTP status + response body
# Last Modified: 2026-09-14 (DWB-509)


class TestTokenIncrementPayloadValidation:
    def test_missing_tokens_used_is_422(self, client, make_agent, make_ticket):
        """No tokens_used key -> 422 (previously bound 0, incremented 0, 200)."""
        agent = make_agent()
        ticket = make_ticket(
            project_id=agent["project_id"], assigned_agent_id=agent["id"]
        )
        r = client.post(
            f"/api/tickets/{ticket['id']}/tokens",
            json={"time_spent_seconds": 30},
        )
        assert r.status_code == 422, r.text

    def test_unknown_key_is_422(self, client, make_agent, make_ticket):
        """A mistyped/extra key -> 422 rather than a silent 0-increment. This is
        the real-world bug: sender posts {tokens: 500} (wrong key), the value is
        dropped, tokens_used defaults to 0, and the caller believes it landed."""
        agent = make_agent()
        ticket = make_ticket(
            project_id=agent["project_id"], assigned_agent_id=agent["id"]
        )
        r = client.post(
            f"/api/tickets/{ticket['id']}/tokens",
            json={"tokens": 500, "time_spent_seconds": 30},
        )
        assert r.status_code == 422, r.text

    def test_success_echoes_applied_increment(
        self, client, make_agent, make_ticket
    ):
        """Success echoes applied_tokens / applied_time_spent_seconds alongside
        the ticket's cumulative fields."""
        agent = make_agent()
        ticket = make_ticket(
            project_id=agent["project_id"], assigned_agent_id=agent["id"]
        )
        r = client.post(
            f"/api/tickets/{ticket['id']}/tokens",
            json={"tokens_used": 500, "time_spent_seconds": 30},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["applied_tokens"] == 500
        assert body["applied_time_spent_seconds"] == 30
        # Cumulative ticket fields still present (TicketRead contract preserved).
        assert body["tokens_used"] == 500
        assert body["token_source"] == "ticket_report"

    def test_explicit_zero_is_valid_and_visible(
        self, client, make_ticket
    ):
        """A time-only report posts explicit tokens_used=0 - still valid (200),
        and the echoed applied_tokens=0 makes the zero-effect visible."""
        ticket = make_ticket()  # unassigned; 0 tokens needs no attribution
        r = client.post(
            f"/api/tickets/{ticket['id']}/tokens",
            json={"tokens_used": 0, "time_spent_seconds": 45},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["applied_tokens"] == 0
        assert body["applied_time_spent_seconds"] == 45
        assert body["time_spent_seconds"] == 45
