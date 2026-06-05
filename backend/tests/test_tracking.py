# Path:          tests/test_tracking.py
# File:          test_tracking.py
# Created:       2026-03-30
# Purpose:       Tests for tracking service — start/stop, token reports, summary, auto-insert
# Caller:        pytest
# Callees:       POST /api/tracking/start|stop|tokens|overhead/start|overhead/stop,
#                GET /api/tracking/summary, PATCH /api/tickets/:id
# Data In:       Factory-created projects, agents, tickets via conftest fixtures
# Data Out:      Assertions on tracking events, summary aggregations, auto-insert behavior
# Last Modified: 2026-03-30

"""Tests for /api/tracking endpoints and auto-tracking on ticket status changes."""

import time


class TestTrackingLogInsert:
    """Verify tracking_log rows are created with correct fields."""

    def test_start_returns_201(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        r = client.post("/api/tracking/start", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
        })
        assert r.status_code == 201

    def test_start_fields(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        data = client.post("/api/tracking/start", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
        }).json()
        assert data["event_type"] == "start"
        assert "id" in data
        assert "timestamp" in data

    def test_stop_returns_201(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        r = client.post("/api/tracking/stop", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
        })
        assert r.status_code == 201
        assert r.json()["event_type"] == "stop"

    def test_token_report_returns_201(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        r = client.post("/api/tracking/tokens", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
            "tokens": 5000, "source": "manual",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["event_type"] == "token_report"
        assert data["tokens"] == 5000

    def test_start_404_for_missing_ticket(self, client, make_agent):
        agent = make_agent()
        r = client.post("/api/tracking/start", json={
            "ticket_id": 999999, "agent_id": agent["id"],
        })
        assert r.status_code == 404

    def test_tokens_404_for_missing_ticket(self, client, make_agent):
        agent = make_agent()
        r = client.post("/api/tracking/tokens", json={
            "ticket_id": 999999, "agent_id": agent["id"],
            "tokens": 100, "source": "manual",
        })
        assert r.status_code == 404


class TestOverhead:
    """Overhead start/stop events (no ticket)."""

    def test_overhead_start_returns_201(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/tracking/overhead/start", json={
            "project_id": project["id"], "agent_id": agent["id"],
        })
        assert r.status_code == 201
        assert r.json()["event_type"] == "overhead_start"

    def test_overhead_stop_returns_201(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/tracking/overhead/stop", json={
            "project_id": project["id"], "agent_id": agent["id"],
        })
        assert r.status_code == 201
        assert r.json()["event_type"] == "overhead_stop"

    def test_overhead_404_for_missing_project(self, client, make_agent):
        agent = make_agent()
        r = client.post("/api/tracking/overhead/start", json={
            "project_id": 999999, "agent_id": agent["id"],
        })
        assert r.status_code == 404


class TestSummary:
    """GET /api/tracking/summary — aggregations."""

    def test_summary_returns_200(self, client, make_project):
        project = make_project()
        r = client.get("/api/tracking/summary", params={"project_id": project["id"]})
        assert r.status_code == 200

    def test_summary_shape(self, client, make_project):
        project = make_project()
        data = client.get("/api/tracking/summary", params={"project_id": project["id"]}).json()
        assert "per_ticket" in data
        assert "per_agent" in data
        assert "per_sprint" in data
        assert "project_total" in data
        total = data["project_total"]
        assert "time_seconds" in total
        assert "tokens" in total
        assert "overhead_time_seconds" in total
        assert "overhead_tokens" in total

    def test_summary_empty_project(self, client, make_project):
        project = make_project()
        data = client.get("/api/tracking/summary", params={"project_id": project["id"]}).json()
        assert data["per_ticket"] == []
        assert data["per_agent"] == []
        assert data["per_sprint"] == []
        assert data["project_total"]["time_seconds"] == 0
        assert data["project_total"]["tokens"] == 0

    def test_summary_404_for_missing_project(self, client):
        r = client.get("/api/tracking/summary", params={"project_id": 999999})
        assert r.status_code == 404

    def test_summary_per_ticket_shape(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        client.post("/api/tracking/start", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
        })
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        assert len(data["per_ticket"]) >= 1
        entry = data["per_ticket"][0]
        assert "ticket_id" in entry
        assert "ticket_key" in entry
        assert "time_seconds" in entry
        assert "tokens" in entry
        assert "agent" in entry

    def test_summary_per_agent_shape(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        client.post("/api/tracking/start", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
        })
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        assert len(data["per_agent"]) >= 1
        entry = data["per_agent"][0]
        # DWB-306: per_agent now exposes `overhead_tokens` breakdown alongside
        # the total `tokens` field.
        expected_keys = {"agent_id", "name", "role", "time_seconds", "tokens", "overhead_tokens"}
        assert set(entry.keys()) == expected_keys

    def test_summary_tokens_summed(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        client.post("/api/tracking/tokens", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
            "tokens": 1000, "source": "manual",
        })
        client.post("/api/tracking/tokens", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
            "tokens": 2000, "source": "manual",
        })
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        ticket_entry = [t for t in data["per_ticket"] if t["ticket_id"] == ticket["id"]]
        assert len(ticket_entry) == 1
        assert ticket_entry[0]["tokens"] == 3000
        assert data["project_total"]["tokens"] == 3000

    def test_summary_per_agent_tokens(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        client.post("/api/tracking/tokens", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
            "tokens": 500, "source": "manual",
        })
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        agent_entry = [a for a in data["per_agent"] if a["agent_id"] == agent["id"]]
        assert len(agent_entry) == 1
        assert agent_entry[0]["tokens"] == 500

    def test_summary_per_sprint(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        client.post("/api/tracking/tokens", json={
            "ticket_id": ticket["id"], "agent_id": agent["id"],
            "tokens": 750, "source": "manual",
        })
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        assert len(data["per_sprint"]) >= 1
        sprint_entry = data["per_sprint"][0]
        assert "sprint_id" in sprint_entry
        assert "name" in sprint_entry
        assert sprint_entry["tokens"] == 750


class TestAutoInsert:
    """Ticket status changes should auto-insert tracking events."""

    def test_in_progress_creates_start_event(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        assert len(data["per_ticket"]) >= 1
        entry = [t for t in data["per_ticket"] if t["ticket_id"] == ticket["id"]]
        assert len(entry) == 1

    def test_done_after_in_progress_creates_stop(self, client, make_ticket, make_agent):
        agent = make_agent()
        ticket = make_ticket(assigned_agent_id=agent["id"])
        # Move to in_progress → should create start
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        time.sleep(1.1)
        # Move to done → should create stop
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"})
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        ticket_entry = [t for t in data["per_ticket"] if t["ticket_id"] == ticket["id"]]
        assert len(ticket_entry) == 1
        assert ticket_entry[0]["time_seconds"] >= 1

    def test_no_event_without_assigned_agent(self, client, make_ticket):
        ticket = make_ticket()
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"})
        project_id = ticket["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()
        assert data["per_ticket"] == []


class TestConsistency:
    """Create known events and verify summary matches expected totals."""

    def test_totals_match_events(self, client, make_ticket, make_agent):
        agent = make_agent()
        t1 = make_ticket(assigned_agent_id=agent["id"])
        t2 = make_ticket(
            project_id=t1["project_id"],
            assigned_agent_id=agent["id"],
        )

        # Log tokens for both tickets
        client.post("/api/tracking/tokens", json={
            "ticket_id": t1["id"], "agent_id": agent["id"],
            "tokens": 1000, "source": "scan",
        })
        client.post("/api/tracking/tokens", json={
            "ticket_id": t1["id"], "agent_id": agent["id"],
            "tokens": 500, "source": "scan",
        })
        client.post("/api/tracking/tokens", json={
            "ticket_id": t2["id"], "agent_id": agent["id"],
            "tokens": 2000, "source": "scan",
        })

        project_id = t1["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()

        # Per-ticket tokens
        t1_entry = [t for t in data["per_ticket"] if t["ticket_id"] == t1["id"]][0]
        t2_entry = [t for t in data["per_ticket"] if t["ticket_id"] == t2["id"]][0]
        assert t1_entry["tokens"] == 1500
        assert t2_entry["tokens"] == 2000

        # Per-agent total
        agent_entry = [a for a in data["per_agent"] if a["agent_id"] == agent["id"]][0]
        assert agent_entry["tokens"] == 3500

        # Project total
        assert data["project_total"]["tokens"] == 3500

        # Cross-check: sum of per-ticket == project total
        ticket_token_sum = sum(t["tokens"] for t in data["per_ticket"])
        assert ticket_token_sum == data["project_total"]["tokens"]

    def test_multi_agent_consistency(self, client, make_ticket, make_agent):
        a1 = make_agent()
        a2 = make_agent()
        t1 = make_ticket(assigned_agent_id=a1["id"])
        t2 = make_ticket(
            project_id=t1["project_id"],
            assigned_agent_id=a2["id"],
        )

        client.post("/api/tracking/tokens", json={
            "ticket_id": t1["id"], "agent_id": a1["id"],
            "tokens": 800, "source": "scan",
        })
        client.post("/api/tracking/tokens", json={
            "ticket_id": t2["id"], "agent_id": a2["id"],
            "tokens": 1200, "source": "scan",
        })

        project_id = t1["project_id"]
        data = client.get("/api/tracking/summary", params={"project_id": project_id}).json()

        # Per-agent breakdown
        a1_entry = [a for a in data["per_agent"] if a["agent_id"] == a1["id"]][0]
        a2_entry = [a for a in data["per_agent"] if a["agent_id"] == a2["id"]][0]
        assert a1_entry["tokens"] == 800
        assert a2_entry["tokens"] == 1200

        # Sum of per-agent == project total
        agent_token_sum = sum(a["tokens"] for a in data["per_agent"])
        assert agent_token_sum == data["project_total"]["tokens"]
        assert data["project_total"]["tokens"] == 2000
