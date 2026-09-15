# Path: tests/test_ticket_token_baseline_dwb546.py
# File: test_ticket_token_baseline_dwb546.py
# Created: 2026-09-15
# Purpose: DWB-546: GET /api/projects/{id}/ticket-token-baseline returns per done-ticket token/time rows reusing the tracking attribution, plus per-sprint count/median/mean/p90 aggregates that exclude zero-token attribution gaps.
# Caller: pytest
# Callees: GET /api/projects/{id}/ticket-token-baseline, app.services.ticket_token_baseline, app.services.tracking
# Data In: Factory-created project/epic/sprint/ticket/agent rows plus posted tracking events
# Data Out: Assertions on row shape, filters, aggregate arithmetic, and empty cases
# Last Modified: 2026-09-15 (DWB-546)

"""DWB-546: the token baseline the node-aware comparison will be measured against."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.ticket import Ticket, TicketStatus
from app.models.tracking_log import TrackingLog
from app.services import ticket_token_baseline as svc


def _url(project_id):
    return f"/api/projects/{project_id}/ticket-token-baseline"


@pytest.fixture
def baseline_world(client, db_session, make_project, make_agent, make_epic):
    """One project, two sprints, an agent, and a helper that lands a done
    ticket with a known attributed token total."""
    project = make_project()
    pid = project["id"]
    agent = make_agent(project_id=pid, name="BaselineDev", role="backend-worker",
                       api_key="btb-dev")
    epic = make_epic(project_id=pid)
    sprints = []
    for n in (1, 2):
        s = client.post("/api/sprints", json={
            "project_id": pid, "epic_id": epic["id"], "goal": f"sprint {n}",
            "sprint_number": n, "status": "planned",
        }).json()
        sprints.append(s["id"])

    counter = [0]

    def add_ticket(sprint_id, tokens, *, seconds=0, done=True, completed_at=None):
        counter[0] += 1
        n = counter[0]
        t = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": sprint_id, "epic_id": epic["id"],
            "ticket_key": f"BTB-{n}", "title": f"baseline ticket {n}",
            "assigned_agent_id": agent["id"],
        }).json()
        if tokens:
            r = client.post("/api/tracking/tokens", json={
                "ticket_id": t["id"], "agent_id": agent["id"], "tokens": tokens,
            })
            assert r.status_code in (200, 201), r.text
        if seconds:
            # Post a real start/stop pair, then pin the two timestamps so the
            # paired duration is exactly `seconds` (wall-clock would be ~0).
            for path in ("start", "stop"):
                r = client.post(f"/api/tracking/{path}", json={
                    "ticket_id": t["id"], "agent_id": agent["id"],
                })
                assert r.status_code in (200, 201), r.text
            base = datetime(2026, 9, 1, 12, 0, 0)
            events = db_session.scalars(
                select(TrackingLog)
                .where(TrackingLog.ticket_id == t["id"])
                .where(TrackingLog.event_type.in_(["start", "stop"]))
                .order_by(TrackingLog.id.asc())
            ).all()
            events[0].timestamp = base
            events[-1].timestamp = base + timedelta(seconds=seconds)
            db_session.flush()
        if done:
            row = db_session.get(Ticket, t["id"])
            row.status = TicketStatus.done
            row.completed_at = completed_at or datetime(2026, 9, 10, 9, 0, 0)
            db_session.flush()
        return t

    return {"pid": pid, "agent": agent, "sprints": sprints, "add": add_ticket}


class TestPercentileHelpers:
    def test_median_even_and_odd(self):
        assert svc._median([10, 20, 30]) == 20.0
        assert svc._median([10, 20, 30, 40]) == 25.0

    def test_p90_interpolates(self):
        values = list(range(1, 11))  # 1..10
        assert svc._percentile(values, 0.9) == pytest.approx(9.1)

    def test_single_value_and_empty(self):
        assert svc._percentile([7], 0.9) == 7.0
        assert svc._percentile([], 0.5) == 0.0


class TestPerTicketRows:
    def test_row_shape_and_attribution(self, client, baseline_world):
        w = baseline_world
        w["add"](w["sprints"][0], 1500, seconds=600)
        r = client.get(_url(w["pid"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == w["pid"]
        assert body["ticket_count"] == 1
        row = body["tickets"][0]
        assert set(row.keys()) == {
            "ticket_id", "ticket_key", "sprint_id", "assigned_agent_id",
            "assigned_agent_name", "tokens_used", "stored_tokens_used",
            "time_seconds", "completed_at", "node_aware",
        }
        assert row["ticket_key"] == "BTB-1"
        assert row["tokens_used"] == 1500
        assert row["time_seconds"] == 600
        assert row["assigned_agent_name"] == "BaselineDev"
        assert row["node_aware"] is False

    def test_matches_tracking_summary_for_same_ticket(self, client, baseline_world):
        """No second implementation: the baseline number equals the tracking
        rollup's number for the same ticket."""
        w = baseline_world
        t = w["add"](w["sprints"][0], 2400)
        baseline = client.get(_url(w["pid"])).json()["tickets"][0]
        summary = client.get("/api/tracking/summary",
                             params={"project_id": w["pid"]}).json()
        tracked = [x for x in summary["per_ticket"] if x["ticket_id"] == t["id"]][0]
        assert baseline["tokens_used"] == tracked["tokens"]
        assert baseline["time_seconds"] == tracked["time_seconds"]

    def test_only_done_tickets_listed(self, client, baseline_world):
        w = baseline_world
        w["add"](w["sprints"][0], 100)
        w["add"](w["sprints"][0], 999, done=False)
        body = client.get(_url(w["pid"])).json()
        assert body["ticket_count"] == 1
        assert body["tickets"][0]["tokens_used"] == 100

    def test_zero_token_ticket_still_listed(self, client, baseline_world):
        """DWB-539 honesty: an unattributed ticket appears, it is not hidden."""
        w = baseline_world
        w["add"](w["sprints"][0], 0)
        body = client.get(_url(w["pid"])).json()
        assert body["ticket_count"] == 1
        assert body["tickets"][0]["tokens_used"] == 0


class TestAggregates:
    def test_known_numbers(self, client, baseline_world):
        w = baseline_world
        for tokens in (100, 200, 300, 400):
            w["add"](w["sprints"][0], tokens)
        body = client.get(_url(w["pid"])).json()
        assert len(body["sprints"]) == 1
        agg = body["sprints"][0]
        assert agg["sprint_id"] == w["sprints"][0]
        assert agg["ticket_count"] == 4
        assert agg["attributed_ticket_count"] == 4
        assert agg["zero_token_ticket_count"] == 0
        assert agg["median_tokens"] == 250.0
        assert agg["mean_tokens"] == 250.0
        assert agg["p90_tokens"] == pytest.approx(370.0)
        assert agg["total_tokens"] == 1000

    def test_zero_tokens_excluded_from_stats_but_counted(self, client, baseline_world):
        w = baseline_world
        for tokens in (100, 300, 0, 0):
            w["add"](w["sprints"][0], tokens)
        agg = client.get(_url(w["pid"])).json()["sprints"][0]
        assert agg["ticket_count"] == 4
        assert agg["attributed_ticket_count"] == 2
        assert agg["zero_token_ticket_count"] == 2
        assert agg["median_tokens"] == 200.0  # not dragged toward 0
        assert agg["mean_tokens"] == 200.0

    def test_split_per_sprint(self, client, baseline_world):
        w = baseline_world
        w["add"](w["sprints"][0], 100)
        w["add"](w["sprints"][1], 500)
        body = client.get(_url(w["pid"])).json()
        by_sprint = {a["sprint_id"]: a for a in body["sprints"]}
        assert by_sprint[w["sprints"][0]]["median_tokens"] == 100.0
        assert by_sprint[w["sprints"][1]]["median_tokens"] == 500.0

    def test_all_zero_sprint_reports_zero_stats(self, client, baseline_world):
        w = baseline_world
        w["add"](w["sprints"][0], 0)
        agg = client.get(_url(w["pid"])).json()["sprints"][0]
        assert agg["attributed_ticket_count"] == 0
        assert agg["median_tokens"] == 0.0
        assert agg["mean_tokens"] == 0.0
        assert agg["p90_tokens"] == 0.0


class TestFilters:
    def test_sprint_filter(self, client, baseline_world):
        w = baseline_world
        w["add"](w["sprints"][0], 100)
        w["add"](w["sprints"][1], 500)
        body = client.get(_url(w["pid"]),
                          params={"sprint_id": w["sprints"][1]}).json()
        assert body["ticket_count"] == 1
        assert body["tickets"][0]["tokens_used"] == 500
        assert len(body["sprints"]) == 1

    def test_since_filter(self, client, baseline_world):
        w = baseline_world
        w["add"](w["sprints"][0], 100,
                 completed_at=datetime(2026, 9, 1, 8, 0, 0))
        w["add"](w["sprints"][0], 700,
                 completed_at=datetime(2026, 9, 20, 8, 0, 0))
        body = client.get(_url(w["pid"]),
                          params={"since": "2026-09-10T00:00:00"}).json()
        assert body["ticket_count"] == 1
        assert body["tickets"][0]["tokens_used"] == 700

    def test_empty_sprint_returns_empty_lists(self, client, baseline_world):
        w = baseline_world
        w["add"](w["sprints"][0], 100)
        body = client.get(_url(w["pid"]),
                          params={"sprint_id": w["sprints"][1]}).json()
        assert body["ticket_count"] == 0
        assert body["tickets"] == []
        assert body["sprints"] == []

    def test_unknown_project_404(self, client):
        r = client.get(_url(999999))
        assert r.status_code == 404
