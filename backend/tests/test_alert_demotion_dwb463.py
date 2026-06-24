# Path: tests/test_alert_demotion_dwb463.py
# File: test_alert_demotion_dwb463.py
# Created: 2026-06-24
# Purpose: Verify peer-scoring / sprint-close / test-run are demoted from alerts to activity-feed actions (DWB-463)
# Caller: pytest
# Callees: POST /api/projects/{id}/scores/peer + /award, PATCH /api/sprints/{id}, POST /api/alerts/run-tests, GET activity-feed
# Data In: factory-created projects/agents/sprints
# Data Out: Assertions that the three types create no alerts but DO record feed events; human scoring still alerts
# Last Modified: 2026-06-24

"""DWB-463 coverage: alerts-vs-actions demotion (epic 37).

Three event types stop creating Alert rows and instead record to the activity
feed:
  - peer carrot/stick  -> score_awarded / score_docked (source=peer)
  - sprint-close notice -> tests_requested
  - ad-hoc test-run     -> test_run_requested

Human scoring is NOT demoted (regression guard) - it still alerts.
"""

import pytest

from app.models.alert import Alert


def _feed_actions(client, pid):
    return [e.get("action") for e in client.get(f"/api/projects/{pid}/activity-feed").json()]


@pytest.fixture
def two_member_project(client, make_project, make_agent, make_project_agent):
    project = make_project()
    a1 = make_agent(name="DemoActor_463")
    a2 = make_agent(name="DemoSubject_463")
    make_project_agent(project_id=project["id"], agent_id=a1["id"])
    make_project_agent(project_id=project["id"], agent_id=a2["id"])
    return {"pid": project["id"], "a1": a1["id"], "a2": a2["id"]}


class TestPeerScoringDemoted:
    def test_peer_creates_no_alert_but_records_feed(self, client, db_session, two_member_project):
        from sqlalchemy import select

        pid, a1, a2 = two_member_project["pid"], two_member_project["a1"], two_member_project["a2"]
        r = client.post(f"/api/projects/{pid}/scores/peer",
                        json={"subject": str(a2), "delta": 3, "reason": "nice fix"},
                        headers={"X-Agent-ID": str(a1)})
        assert r.status_code == 201
        assert r.json()["broadcast_count"] == 0

        alerts = db_session.scalars(
            select(Alert).where(Alert.project_id == pid)
        ).all()
        assert alerts == []
        assert "score_awarded" in _feed_actions(client, pid)


class TestHumanScoringStillAlerts:
    def test_human_award_still_creates_alerts(self, client, db_session, two_member_project):
        from sqlalchemy import select

        pid, a2 = two_member_project["pid"], two_member_project["a2"]
        r = client.post(f"/api/projects/{pid}/scores/award",
                        json={"agent": "DemoSubject_463", "delta": 5, "reason": "great"})
        assert r.status_code == 201
        assert r.json()["broadcast_count"] >= 1
        alerts = db_session.scalars(
            select(Alert).where(Alert.project_id == pid)
        ).all()
        assert alerts  # human scoring is NOT demoted
        assert all(a.category.value == "scoring" for a in alerts)


class TestSprintCloseDemoted:
    def test_sprint_close_creates_no_alert_existing_feed_event_covers_it(
        self, client, make_project, make_epic, make_agent, make_project_agent
    ):
        # DWB-463: the "tests needed" alert rows are removed. No NEW feed verb
        # is added - the existing sprint_closed event (DWB-410) already
        # represents the close, so we must not duplicate it.
        project = make_project()
        tester = make_agent(name="DemoTester_463", role="tester")
        make_project_agent(project_id=project["id"], agent_id=tester["id"])
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 1, "status": "active",
        }).json()

        before = client.get("/api/alerts", params={"project_id": project["id"]}).json()
        client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        after = client.get("/api/alerts", params={"project_id": project["id"]}).json()

        new = [a for a in after if a["id"] not in {x["id"] for x in before}]
        assert all("tests needed" not in a["title"].lower() for a in new)
        actions = _feed_actions(client, project["id"])
        assert "sprint_closed" in actions
        assert "tests_requested" not in actions


class TestTestRunDemoted:
    def test_run_tests_records_feed_not_alert(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        before = client.get("/api/alerts", params={"project_id": project["id"]}).json()
        r = client.post("/api/alerts/run-tests", json={
            "project_id": project["id"], "raised_by_agent_id": agent["id"],
        })
        assert r.status_code == 201
        assert r.json()["action"] == "test_run_requested"
        after = client.get("/api/alerts", params={"project_id": project["id"]}).json()
        assert len(after) == len(before)
        assert "test_run_requested" in _feed_actions(client, project["id"])
