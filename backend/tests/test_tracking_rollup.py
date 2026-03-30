# Path:          tests/test_tracking_rollup.py
# File:          test_tracking_rollup.py
# Created:       2026-03-30
# Purpose:       Functional rollup + consistency tests for tracking summary aggregations
# Caller:        pytest
# Callees:       POST /api/tracking/start|stop|tokens|overhead/start|overhead/stop,
#                GET /api/tracking/summary
# Data In:       Factory-created projects, agents, epics, sprints, tickets via conftest fixtures
# Data Out:      Assertions on exact summary numbers at every aggregation level
# Last Modified: 2026-03-30

"""DWB-203 / DWB-204: Functional rollup and consistency tests for tracking summary."""

import time
from datetime import datetime, timedelta

from app.models.tracking_log import TrackingLog


class TestFunctionalRollup:
    """DWB-203: Full scenario with known events, verify exact numbers."""

    def _setup_scenario(self, client, make_project, make_agent, make_epic, make_sprint, make_ticket):
        """Create project with 2 agents, 2 sprints, 3 tickets, return all IDs."""
        project = make_project()
        pid = project["id"]
        agent1 = make_agent(name="Dev1", role="developer")
        agent2 = make_agent(name="Dev2", role="developer")
        epic = make_epic(project_id=pid)
        s1 = make_sprint(project_id=pid, epic_id=epic["id"], sprint_number=100)
        s2 = make_sprint(project_id=pid, epic_id=epic["id"], sprint_number=101)

        t1 = make_ticket(project_id=pid, sprint_id=s1["id"], assigned_agent_id=agent1["id"])
        t2 = make_ticket(project_id=pid, sprint_id=s1["id"], assigned_agent_id=agent2["id"])
        t3 = make_ticket(project_id=pid, sprint_id=s2["id"], assigned_agent_id=agent1["id"])

        return {
            "project_id": pid,
            "agent1": agent1, "agent2": agent2,
            "sprint1": s1, "sprint2": s2,
            "ticket1": t1, "ticket2": t2, "ticket3": t3,
        }

    def test_exact_token_rollup(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        s = self._setup_scenario(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        pid = s["project_id"]

        # Post known token events
        # t1 (agent1, sprint1): 1000 + 500 = 1500
        client.post("/api/tracking/tokens", json={
            "ticket_id": s["ticket1"]["id"], "agent_id": s["agent1"]["id"],
            "tokens": 1000, "source": "scan",
        })
        client.post("/api/tracking/tokens", json={
            "ticket_id": s["ticket1"]["id"], "agent_id": s["agent1"]["id"],
            "tokens": 500, "source": "scan",
        })
        # t2 (agent2, sprint1): 2000
        client.post("/api/tracking/tokens", json={
            "ticket_id": s["ticket2"]["id"], "agent_id": s["agent2"]["id"],
            "tokens": 2000, "source": "scan",
        })
        # t3 (agent1, sprint2): 3000
        client.post("/api/tracking/tokens", json={
            "ticket_id": s["ticket3"]["id"], "agent_id": s["agent1"]["id"],
            "tokens": 3000, "source": "scan",
        })

        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()

        # Per-ticket
        t1_e = [t for t in data["per_ticket"] if t["ticket_id"] == s["ticket1"]["id"]][0]
        t2_e = [t for t in data["per_ticket"] if t["ticket_id"] == s["ticket2"]["id"]][0]
        t3_e = [t for t in data["per_ticket"] if t["ticket_id"] == s["ticket3"]["id"]][0]
        assert t1_e["tokens"] == 1500
        assert t2_e["tokens"] == 2000
        assert t3_e["tokens"] == 3000

        # Per-agent: agent1 = 1500+3000=4500, agent2 = 2000
        a1_e = [a for a in data["per_agent"] if a["agent_id"] == s["agent1"]["id"]][0]
        a2_e = [a for a in data["per_agent"] if a["agent_id"] == s["agent2"]["id"]][0]
        assert a1_e["tokens"] == 4500
        assert a2_e["tokens"] == 2000

        # Per-sprint: sprint1 = 1500+2000=3500, sprint2 = 3000
        s1_e = [sp for sp in data["per_sprint"] if sp["sprint_id"] == s["sprint1"]["id"]][0]
        s2_e = [sp for sp in data["per_sprint"] if sp["sprint_id"] == s["sprint2"]["id"]][0]
        assert s1_e["tokens"] == 3500
        assert s2_e["tokens"] == 3000

        # Project total
        assert data["project_total"]["tokens"] == 6500

    def test_time_from_start_stop_pairs(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        s = self._setup_scenario(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        pid = s["project_id"]
        tid = s["ticket1"]["id"]
        aid = s["agent1"]["id"]

        # Start, wait, stop — should record >= 1s
        client.post("/api/tracking/start", json={"ticket_id": tid, "agent_id": aid})
        time.sleep(1.1)
        client.post("/api/tracking/stop", json={"ticket_id": tid, "agent_id": aid})

        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        t1_e = [t for t in data["per_ticket"] if t["ticket_id"] == tid][0]
        assert t1_e["time_seconds"] >= 1
        assert data["project_total"]["time_seconds"] >= 1

    def test_multiple_start_stop_pairs(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        s = self._setup_scenario(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        pid = s["project_id"]
        tid = s["ticket1"]["id"]
        aid = s["agent1"]["id"]

        # Two start/stop pairs
        client.post("/api/tracking/start", json={"ticket_id": tid, "agent_id": aid})
        time.sleep(1.1)
        client.post("/api/tracking/stop", json={"ticket_id": tid, "agent_id": aid})

        client.post("/api/tracking/start", json={"ticket_id": tid, "agent_id": aid})
        time.sleep(1.1)
        client.post("/api/tracking/stop", json={"ticket_id": tid, "agent_id": aid})

        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        t1_e = [t for t in data["per_ticket"] if t["ticket_id"] == tid][0]
        assert t1_e["time_seconds"] >= 2

    def test_open_interval_not_counted(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        """A start without a matching stop should not contribute time."""
        s = self._setup_scenario(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        pid = s["project_id"]
        tid = s["ticket1"]["id"]
        aid = s["agent1"]["id"]

        # Only a start — no stop
        client.post("/api/tracking/start", json={"ticket_id": tid, "agent_id": aid})

        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        t1_e = [t for t in data["per_ticket"] if t["ticket_id"] == tid][0]
        assert t1_e["time_seconds"] == 0

    def test_no_events_returns_empty(self, client, make_project):
        project = make_project()
        data = client.get("/api/tracking/summary", params={"project_id": project["id"]}).json()
        assert data["per_ticket"] == []
        assert data["per_agent"] == []
        assert data["per_sprint"] == []
        assert data["project_total"]["time_seconds"] == 0
        assert data["project_total"]["tokens"] == 0
        assert data["project_total"]["overhead_time_seconds"] == 0


class TestConsistencyInvariants:
    """DWB-204: Summary cross-check invariants."""

    def _seed_data(self, client, make_project, make_agent, make_epic, make_sprint, make_ticket):
        """Create a project with mixed data for invariant testing."""
        project = make_project()
        pid = project["id"]
        a1 = make_agent()
        a2 = make_agent()
        epic = make_epic(project_id=pid)
        s1 = make_sprint(project_id=pid, epic_id=epic["id"], sprint_number=200)
        s2 = make_sprint(project_id=pid, epic_id=epic["id"], sprint_number=201)

        t1 = make_ticket(project_id=pid, sprint_id=s1["id"], assigned_agent_id=a1["id"])
        t2 = make_ticket(project_id=pid, sprint_id=s1["id"], assigned_agent_id=a2["id"])
        t3 = make_ticket(project_id=pid, sprint_id=s2["id"], assigned_agent_id=a1["id"])

        # Tokens
        for tid, aid, tok in [
            (t1["id"], a1["id"], 1000),
            (t1["id"], a1["id"], 200),
            (t2["id"], a2["id"], 3000),
            (t3["id"], a1["id"], 500),
        ]:
            client.post("/api/tracking/tokens", json={
                "ticket_id": tid, "agent_id": aid, "tokens": tok, "source": "scan",
            })

        # Time: start/stop on t1
        client.post("/api/tracking/start", json={"ticket_id": t1["id"], "agent_id": a1["id"]})
        time.sleep(1.1)
        client.post("/api/tracking/stop", json={"ticket_id": t1["id"], "agent_id": a1["id"]})

        return pid, a1, a2

    def test_per_ticket_tokens_eq_project_total(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, _, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert sum(t["tokens"] for t in data["per_ticket"]) == data["project_total"]["tokens"]

    def test_per_agent_tokens_eq_project_total(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, _, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert sum(a["tokens"] for a in data["per_agent"]) == data["project_total"]["tokens"]

    def test_per_sprint_tokens_eq_project_total(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, _, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert sum(s["tokens"] for s in data["per_sprint"]) == data["project_total"]["tokens"]

    def test_per_ticket_time_eq_project_total(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, _, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert sum(t["time_seconds"] for t in data["per_ticket"]) == data["project_total"]["time_seconds"]

    def test_per_agent_time_eq_project_total(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, _, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert sum(a["time_seconds"] for a in data["per_agent"]) == data["project_total"]["time_seconds"]

    def test_per_sprint_time_eq_project_total(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, _, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert sum(s["time_seconds"] for s in data["per_sprint"]) == data["project_total"]["time_seconds"]

    def test_overhead_not_in_per_ticket(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, a1, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)

        # Add overhead
        client.post("/api/tracking/overhead/start", json={
            "project_id": pid, "agent_id": a1["id"],
        })
        time.sleep(1.1)
        client.post("/api/tracking/overhead/stop", json={
            "project_id": pid, "agent_id": a1["id"],
        })

        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()

        # Overhead should be separate
        assert data["project_total"]["overhead_time_seconds"] >= 1

        # per_ticket time should NOT include overhead
        ticket_time_sum = sum(t["time_seconds"] for t in data["per_ticket"])
        assert ticket_time_sum == data["project_total"]["time_seconds"]
        # overhead is additive, not part of time_seconds
        assert data["project_total"]["overhead_time_seconds"] > 0

    def test_overhead_not_in_per_sprint(
        self, client, make_project, make_agent, make_epic, make_sprint, make_ticket
    ):
        pid, a1, _ = self._seed_data(client, make_project, make_agent, make_epic, make_sprint, make_ticket)

        client.post("/api/tracking/overhead/start", json={
            "project_id": pid, "agent_id": a1["id"],
        })
        time.sleep(1.1)
        client.post("/api/tracking/overhead/stop", json={
            "project_id": pid, "agent_id": a1["id"],
        })

        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()

        sprint_time_sum = sum(s["time_seconds"] for s in data["per_sprint"])
        # Sprint time should equal project time (not include overhead)
        assert sprint_time_sum == data["project_total"]["time_seconds"]
