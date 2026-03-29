"""Tests for /api/tokens/audit endpoint."""


class TestTokenAudit:
    def test_audit_returns_200(self, client):
        r = client.get("/api/tokens/audit")
        assert r.status_code == 200

    def test_audit_response_shape(self, client):
        data = client.get("/api/tokens/audit").json()
        expected_keys = {
            "total_ticket_tokens", "tokens_by_agent",
            "tokens_by_project", "discrepancies",
        }
        assert set(data.keys()) == expected_keys

    def test_audit_empty_db_returns_zeroes(self, client):
        data = client.get("/api/tokens/audit").json()
        assert data["total_ticket_tokens"] == 0
        assert data["tokens_by_agent"] == []
        assert data["discrepancies"] == []

    def test_audit_tokens_by_project_shape(self, client, make_project):
        make_project()
        data = client.get("/api/tokens/audit").json()
        assert len(data["tokens_by_project"]) >= 1
        proj = data["tokens_by_project"][0]
        expected_keys = {
            "project_id", "prefix", "ticket_tokens",
            "tl_overhead", "pm_overhead", "total",
        }
        assert set(proj.keys()) == expected_keys

    def test_audit_tokens_by_agent_shape(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        # Add tokens to the ticket
        client.patch(f"/api/tickets/{ticket['id']}", json={
            "tokens_used": 500,
        })
        data = client.get("/api/tokens/audit").json()
        assert len(data["tokens_by_agent"]) >= 1
        agent_entry = data["tokens_by_agent"][0]
        expected_keys = {"agent_id", "name", "role", "total_tokens"}
        assert set(agent_entry.keys()) == expected_keys

    def test_audit_totals_add_up(self, client, make_project, make_ticket, make_agent):
        project = make_project()
        agent = make_agent()
        t1 = make_ticket(
            project_id=project["id"],
            assigned_agent_id=agent["id"],
        )
        t2 = make_ticket(
            project_id=project["id"],
            assigned_agent_id=agent["id"],
        )
        client.patch(f"/api/tickets/{t1['id']}", json={"tokens_used": 100})
        client.patch(f"/api/tickets/{t2['id']}", json={"tokens_used": 200})
        data = client.get("/api/tokens/audit").json()
        assert data["total_ticket_tokens"] >= 300

    def test_audit_includes_overhead(self, client, make_project):
        project = make_project()
        # Add overhead tokens
        client.post(f"/api/projects/{project['id']}/overhead", json={
            "role": "team_lead",
            "tokens_used": 1000,
        })
        data = client.get("/api/tokens/audit").json()
        proj_entry = [
            p for p in data["tokens_by_project"]
            if p["project_id"] == project["id"]
        ]
        assert len(proj_entry) == 1
        assert proj_entry[0]["tl_overhead"] == 1000
        assert proj_entry[0]["total"] >= 1000
