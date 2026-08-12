# Path:          tests/test_token_attribution.py
# File:          test_token_attribution.py
# Created:       2026-03-28
# Purpose:       Tests for token attribution endpoint and token_source field
# Caller:        pytest
# Callees:       GET /api/tickets/:id/token-attribution, POST /api/tickets/:id/tokens
# Data In:       Factory-created tickets via conftest fixtures
# Data Out:      Assertions on attribution shape, source values, and token accumulation
# Last Modified: 2026-08-12 (DWB-022: token reports need an attributable agent + never leave source 'unknown')

"""Tests for token attribution endpoint and token_source field."""


class TestTokenAttribution:
    def test_attribution_returns_200(self, client, make_ticket):
        ticket = make_ticket()
        r = client.get(f"/api/tickets/{ticket['id']}/token-attribution")
        assert r.status_code == 200

    def test_attribution_response_shape(self, client, make_ticket):
        ticket = make_ticket()
        data = client.get(f"/api/tickets/{ticket['id']}/token-attribution").json()
        expected_keys = {"ticket_key", "tokens_used", "time_spent_seconds", "source", "history"}
        assert set(data.keys()) == expected_keys

    def test_attribution_reflects_ticket_data(self, client, make_agent, make_ticket):
        # DWB-022: a token report needs an attributable agent (the assignee here).
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 500,
            "time_spent_seconds": 30,
            "source": "claude-api",
        })
        data = client.get(f"/api/tickets/{ticket['id']}/token-attribution").json()
        assert data["ticket_key"] == ticket["ticket_key"]
        assert data["tokens_used"] == 500
        assert data["time_spent_seconds"] == 30
        assert data["source"] == "claude-api"

    def test_attribution_default_source_unknown(self, client, make_ticket):
        ticket = make_ticket()
        data = client.get(f"/api/tickets/{ticket['id']}/token-attribution").json()
        assert data["source"] == "unknown"

    def test_attribution_404_nonexistent(self, client):
        r = client.get("/api/tickets/999999/token-attribution")
        assert r.status_code == 404


class TestTokenSource:
    def test_token_source_in_ticket_response(self, client, make_ticket):
        ticket = make_ticket()
        data = client.get(f"/api/tickets/{ticket['id']}").json()
        assert "token_source" in data

    def test_token_source_default_unknown(self, client, make_ticket):
        ticket = make_ticket()
        data = client.get(f"/api/tickets/{ticket['id']}").json()
        assert data["token_source"] == "unknown"

    def test_tokens_endpoint_sets_source(self, client, make_agent, make_ticket):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        r = client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 100,
            "source": "claude-api",
        })
        assert r.status_code == 200
        assert r.json()["token_source"] == "claude-api"

    def test_tokens_endpoint_without_source(self, client, make_agent, make_ticket):
        # DWB-022: with no declared source the write stamps the explicit-report
        # label 'ticket_report' - NEVER the 'unknown' default (the phantom bug).
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        r = client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 100,
        })
        assert r.status_code == 200
        assert r.json()["token_source"] == "ticket_report"

    def test_source_updated_on_subsequent_call(self, client, make_agent, make_ticket):
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 100,
            "source": "claude-api",
        })
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 50,
            "source": "openai-api",
        })
        data = client.get(f"/api/tickets/{ticket['id']}").json()
        assert data["token_source"] == "openai-api"
        assert data["tokens_used"] == 150

    def test_source_preserved_when_not_provided(self, client, make_agent, make_ticket):
        # A meaningful existing source is kept when a later report omits source
        # (we don't clobber 'claude-api' with the generic 'ticket_report').
        agent = make_agent()
        ticket = make_ticket(project_id=agent["project_id"], assigned_agent_id=agent["id"])
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 100,
            "source": "claude-api",
        })
        # Second call without source — existing meaningful source preserved.
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 50,
        })
        data = client.get(f"/api/tickets/{ticket['id']}").json()
        assert data["token_source"] == "claude-api"
        assert data["tokens_used"] == 150
