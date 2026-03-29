"""Tests for auto-alert when ticket closed with tokens_used=0."""


class TestTokenAlertOnClose:
    def test_closing_with_zero_tokens_creates_info_alert(
        self, client, make_ticket, make_agent
    ):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        assert ticket["tokens_used"] == 0

        r = client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        assert r.status_code == 200

        alerts = client.get("/api/alerts", params={
            "project_id": ticket["project_id"],
        }).json()
        matching = [
            a for a in alerts
            if a.get("ticket_id") == ticket["id"]
            and a["severity"] == "info"
            and "Tokens not reported" in a["title"]
        ]
        assert len(matching) == 1
        alert = matching[0]
        assert alert["status"] == "open"
        assert alert["raised_by_agent_id"] == agent["id"]

    def test_closing_with_tokens_does_not_create_alert(
        self, client, make_ticket, make_agent
    ):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])

        client.post(f"/api/tickets/{ticket['id']}/tokens", json={
            "tokens_used": 500, "time_spent_seconds": 30,
        })
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        alerts = client.get("/api/alerts", params={
            "project_id": ticket["project_id"],
        }).json()
        matching = [
            a for a in alerts
            if a.get("ticket_id") == ticket["id"]
            and "Tokens not reported" in a.get("title", "")
        ]
        assert len(matching) == 0

    def test_no_alert_when_no_assigned_agent(self, client, make_ticket):
        ticket = make_ticket()
        assert ticket["assigned_agent_id"] is None

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        alerts = client.get("/api/alerts", params={
            "project_id": ticket["project_id"],
        }).json()
        matching = [
            a for a in alerts
            if a.get("ticket_id") == ticket["id"]
            and "Tokens not reported" in a.get("title", "")
        ]
        assert len(matching) == 0

    def test_alert_references_correct_ticket_key(
        self, client, make_ticket, make_agent
    ):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        alerts = client.get("/api/alerts", params={
            "project_id": ticket["project_id"],
        }).json()
        matching = [
            a for a in alerts
            if a.get("ticket_id") == ticket["id"]
            and "Tokens not reported" in a.get("title", "")
        ]
        assert len(matching) == 1
        assert ticket["ticket_key"] in matching[0]["title"]

    def test_non_done_status_does_not_create_alert(
        self, client, make_ticket, make_agent
    ):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})

        alerts = client.get("/api/alerts", params={
            "project_id": ticket["project_id"],
        }).json()
        matching = [
            a for a in alerts
            if a.get("ticket_id") == ticket["id"]
            and "Tokens not reported" in a.get("title", "")
        ]
        assert len(matching) == 0

    def test_alert_body_mentions_tokens_endpoint(
        self, client, make_ticket, make_agent
    ):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])

        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})

        alerts = client.get("/api/alerts", params={
            "project_id": ticket["project_id"],
        }).json()
        matching = [
            a for a in alerts
            if a.get("ticket_id") == ticket["id"]
            and "Tokens not reported" in a.get("title", "")
        ]
        assert len(matching) == 1
        assert "/api/tickets/" in matching[0]["body"]
        assert "tokens" in matching[0]["body"]
