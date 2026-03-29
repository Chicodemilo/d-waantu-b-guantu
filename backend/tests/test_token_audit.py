"""Tests for GET /api/tokens/audit (Sprint 13)."""


class TestTokenAudit:
    def test_returns_200(self, client):
        r = client.get("/api/tokens/audit")
        assert r.status_code == 200

    def test_response_shape(self, client):
        data = client.get("/api/tokens/audit").json()
        assert "total_ticket_tokens" in data
        assert "tokens_by_agent" in data
        assert "tokens_by_project" in data
        assert "discrepancies" in data
        assert isinstance(data["tokens_by_agent"], list)
        assert isinstance(data["tokens_by_project"], list)
        assert isinstance(data["discrepancies"], list)

    def test_tokens_by_project_shape(self, client, make_project):
        make_project()
        data = client.get("/api/tokens/audit").json()
        assert len(data["tokens_by_project"]) >= 1
        entry = data["tokens_by_project"][0]
        expected_keys = {"project_id", "prefix", "ticket_tokens", "tl_overhead", "pm_overhead", "total"}
        assert set(entry.keys()) == expected_keys

    def test_tokens_by_agent_shape(self, client, make_ticket, make_agent, make_project_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        # Add some tokens
        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 500, "time_spent_seconds": 30,
        })

        data = client.get("/api/tokens/audit").json()
        agent_entries = [a for a in data["tokens_by_agent"] if a["agent_id"] == agent["id"]]
        assert len(agent_entries) == 1
        entry = agent_entries[0]
        expected_keys = {"agent_id", "name", "role", "total_tokens"}
        assert set(entry.keys()) == expected_keys
        assert entry["total_tokens"] >= 500

    def test_totals_add_up(self, client, make_ticket, make_agent):
        agent = make_agent()
        t1 = make_ticket(assigned_agent_id=agent["id"])
        t2 = make_ticket(assigned_agent_id=agent["id"])
        client.post(f"/api/tickets/{t1['id']}/tokens", json={
            "tokens_used": 1000, "time_spent_seconds": 60,
        })
        client.post(f"/api/tickets/{t2['id']}/tokens", json={
            "tokens_used": 2000, "time_spent_seconds": 120,
        })

        data = client.get("/api/tokens/audit").json()
        # Project ticket token sums should equal total
        project_ticket_sum = sum(p["ticket_tokens"] for p in data["tokens_by_project"])
        assert project_ticket_sum == data["total_ticket_tokens"]

    def test_empty_database_returns_zeroes(self, client):
        data = client.get("/api/tokens/audit").json()
        assert data["total_ticket_tokens"] == 0
        assert data["tokens_by_agent"] == []
        assert data["discrepancies"] == []
