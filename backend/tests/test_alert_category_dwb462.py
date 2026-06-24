# Path: tests/test_alert_category_dwb462.py
# File: test_alert_category_dwb462.py
# Created: 2026-06-24
# Purpose: Tests for the alert category taxonomy (comms/scoring/actionable) + count scoping + filter (DWB-462)
# Caller: pytest
# Callees: POST/GET /api/alerts, GET /api/status, tl_channel.send_message, scoring.broadcast_score_change, ticket rework path
# Data In: factory-created projects/agents/tickets, direct service calls
# Data Out: Assertions on Alert.category at each kept site, schema default, /api/alerts filter, /api/status open_alerts scoping
# Last Modified: 2026-06-24

"""DWB-462 coverage.

The alerts-vs-actions taxonomy adds an Alert.category enum. This file pins:
  - the schema default (actionable) + explicit category round-trips via the API;
  - the category filter on GET /api/alerts;
  - the four kept sites classify correctly: TL-channel ping -> comms,
    human/peer scoring broadcast -> scoring, missing gate file -> actionable,
    rework -> actionable;
  - GET /api/status open_alerts counts only categorized alerts.
"""

import pytest

from app.models.alert import Alert, AlertCategory, AlertStatus


class TestAlertCategoryApi:
    def test_create_defaults_to_actionable(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Something", "body": "Body",
        })
        assert r.status_code == 201
        assert r.json()["category"] == "actionable"

    def test_create_with_explicit_category(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        r = client.post("/api/alerts", json={
            "project_id": project["id"],
            "raised_by_agent_id": agent["id"],
            "title": "Comms", "body": "Body",
            "category": "comms",
        })
        assert r.status_code == 201
        assert r.json()["category"] == "comms"

    def test_category_filter(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent()
        for cat in ("comms", "scoring", "actionable"):
            client.post("/api/alerts", json={
                "project_id": project["id"],
                "raised_by_agent_id": agent["id"],
                "title": f"{cat} alert", "body": "Body", "category": cat,
            })
        scoring = client.get("/api/alerts", params={
            "project_id": project["id"], "category": "scoring",
        }).json()
        assert len(scoring) == 1
        assert scoring[0]["category"] == "scoring"


class TestStatusCountScoping:
    def test_open_alerts_counts_categorized_alerts(self, client, make_project, make_agent):
        before = client.get("/api/status").json()["open_alerts"]
        project = make_project()
        agent = make_agent()
        for cat in ("comms", "scoring", "actionable"):
            client.post("/api/alerts", json={
                "project_id": project["id"],
                "raised_by_agent_id": agent["id"],
                "title": f"{cat} alert", "body": "Body", "category": cat,
            })
        after = client.get("/api/status").json()["open_alerts"]
        # all three categories are counted
        assert after == before + 3


class TestKeptSiteCategories:
    def test_tl_channel_ping_is_comms(self, client, db_session, make_project):
        from app.models.agent import Agent
        from app.services import tl_channel

        project = make_project()
        tl1 = Agent(name="ArchieA_462", role="team-lead", api_key="k-462a", project_id=project["id"])
        tl2 = Agent(name="ArchieB_462", role="team-lead", api_key="k-462b", project_id=project["id"])
        db_session.add_all([tl1, tl2])
        db_session.flush()

        tl_channel.send_message(db_session, from_agent=tl1, to_agent=tl2, body="hello")

        alert = db_session.query(Alert).filter(
            Alert.raised_by_agent_id == tl1.id,
            Alert.recipient_agent_id == tl2.id,
        ).one()
        assert alert.category == AlertCategory.comms

    def test_human_scoring_broadcast_is_scoring(self, client, db_session, make_project, make_agent, make_project_agent):
        from app.services import scoring

        project = make_project()
        subject = make_agent()
        make_project_agent(project_id=project["id"], agent_id=subject["id"])

        scoring.broadcast_score_change(
            db_session,
            project_id=project["id"],
            subject_agent_id=subject["id"],
            subject_name=subject["name"],
            delta=3,
            reason="great work",
            source="human",
        )
        db_session.flush()

        alerts = db_session.query(Alert).filter(
            Alert.project_id == project["id"],
        ).all()
        assert alerts
        assert all(a.category == AlertCategory.scoring for a in alerts)

    def test_peer_scoring_broadcast_creates_no_alert(self, client, db_session, make_project, make_agent, make_project_agent):
        # DWB-463: peer scoring is demoted to the activity feed - broadcast
        # creates no alert rows (only human scoring still alerts).
        from app.services import scoring

        project = make_project()
        subject = make_agent()
        actor = make_agent()
        make_project_agent(project_id=project["id"], agent_id=subject["id"])
        make_project_agent(project_id=project["id"], agent_id=actor["id"])

        count = scoring.broadcast_score_change(
            db_session,
            project_id=project["id"],
            subject_agent_id=subject["id"],
            subject_name=subject["name"],
            delta=2,
            reason="nice catch",
            source="peer",
            actor_agent_id=actor["id"],
            actor_name=actor["name"],
        )
        db_session.flush()

        assert count == 0
        alerts = db_session.query(Alert).filter(
            Alert.project_id == project["id"],
        ).all()
        assert alerts == []

    def test_rework_alert_is_actionable(self, client, make_project, make_agent, make_epic):
        # Rework detection requires a PM on the project.
        project = make_project()
        worker = make_agent()
        pm = make_agent(role="pm")
        client.post("/api/project-agents", json={
            "project_id": project["id"], "agent_id": pm["id"],
        })
        epic = make_epic(project_id=project["id"])
        sprint = client.post("/api/sprints", json={
            "project_id": project["id"], "epic_id": epic["id"],
            "sprint_number": 1, "status": "active",
        }).json()
        ticket = client.post("/api/tickets", json={
            "project_id": project["id"], "sprint_id": sprint["id"],
            "ticket_number": 1, "ticket_key": f"{project['prefix']}-001",
            "title": "Rework me", "assigned_agent_id": worker["id"],
        }).json()

        # done, then back to in_progress -> rework alert
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"},
                     headers={"X-Agent-ID": str(worker["id"])})
        client.patch(f"/api/tickets/{ticket['id']}", json={"status": "in_progress"},
                     headers={"X-Agent-ID": str(worker["id"])})

        rework = client.get("/api/alerts", params={
            "project_id": project["id"], "category": "actionable",
        }).json()
        titles = [a["title"] for a in rework]
        assert any("Rework detected" in t for t in titles)

    def test_missing_gate_file_is_actionable(self, client, db_session, make_agent, tmp_path):
        from app.models.project import Project
        from app.routers.projects import _check_doc_gates

        # Project with force_initial_md on and no INITIAL.md on disk.
        proj_row = client.post("/api/projects", json={
            "prefix": "G462", "name": "Gate 462", "repo_path": str(tmp_path),
            "force_initial_md": True, "force_architecture_md": False,
            "force_handoff_md": False, "force_test_run": False,
            "force_test_coverage": False,
        }).json()
        # Assign a TL so the gate alert has a raiser.
        tl = make_agent(role="team-lead")
        client.post("/api/project-agents", json={
            "project_id": proj_row["id"], "agent_id": tl["id"],
        })

        project = db_session.get(Project, proj_row["id"])
        _check_doc_gates(db_session, project)

        gate_alerts = client.get("/api/alerts", params={
            "project_id": proj_row["id"], "category": "actionable",
        }).json()
        assert any("INITIAL.md" in a["title"] for a in gate_alerts)
