# Path:          tests/test_sprint_activity_events.py
# File:          test_sprint_activity_events.py
# Created:       2026-06-19
# Purpose:       Tests for semantic sprint + consolidation activity events (DWB-410)
# Caller:        pytest
# Callees:       POST/PATCH /api/sprints, POST /api/agents/{id}/consolidate-complete, ActivityLog
# Data In:       Factory-created project/epic/sprint/agent, in-process db_session
# Data Out:      Assertions on sprint_opened / sprint_closed / consolidation_acked rows
# Last Modified: 2026-06-19 (DWB-410)

"""Semantic sprint-event tests: sprint_opened, sprint_closed, consolidation_acked."""

import json

from sqlalchemy import select

from app.models.activity_log import ActivityLog


def _events(db_session, entity_type, entity_id, action=None):
    stmt = select(ActivityLog).where(
        ActivityLog.entity_type == entity_type,
        ActivityLog.entity_id == entity_id,
    )
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    return list(db_session.scalars(stmt).all())


def _details(row):
    return json.loads(row.details) if row.details else None


def _gateless_project(client, tmp_path, prefix="SAE"):
    return client.post("/api/projects", json={
        "prefix": prefix,
        "name": f"{prefix} Project",
        "repo_path": str(tmp_path),
        "force_initial_md": False,
        "force_architecture_md": False,
        "force_handoff_md": False,
        "force_test_run": False,
        "force_test_coverage": False,
    }).json()


class TestSprintOpenedEvent:
    def test_create_active_sprint_emits_sprint_opened(self, client, db_session, make_sprint):
        sprint = make_sprint(goal="Ship the activity feed", sprint_number=1)
        assert sprint["status"] == "active"
        rows = _events(db_session, "sprint", sprint["id"], "sprint_opened")
        assert len(rows) == 1
        details = _details(rows[0])
        assert details["sprint_number"] == 1
        assert details["goal"] == "Ship the activity feed"

    def test_create_planned_sprint_does_not_emit(self, client, db_session, make_sprint):
        sprint = make_sprint(status="planned", sprint_number=2)
        assert _events(db_session, "sprint", sprint["id"], "sprint_opened") == []

    def test_patch_planned_to_active_emits_sprint_opened(self, client, db_session, make_sprint, make_agent):
        sprint = make_sprint(status="planned", sprint_number=3)
        agent = make_agent(project_id=sprint["project_id"])
        r = client.patch(
            f"/api/sprints/{sprint['id']}",
            json={"status": "active"},
            headers={"X-Agent-ID": str(agent["id"])},
        )
        assert r.status_code == 200
        rows = _events(db_session, "sprint", sprint["id"], "sprint_opened")
        assert len(rows) == 1
        assert rows[0].agent_id == agent["id"]  # actor threaded from X-Agent-ID


class TestSprintClosedEvent:
    def test_patch_active_to_completed_emits_sprint_closed(self, client, db_session, make_epic, make_sprint, tmp_path):
        project = _gateless_project(client, tmp_path)
        epic = make_epic(project_id=project["id"])
        sprint = make_sprint(project_id=project["id"], epic_id=epic["id"], goal="Close me", sprint_number=1)
        r = client.patch(f"/api/sprints/{sprint['id']}", json={"status": "completed"})
        assert r.status_code == 200, r.text
        rows = _events(db_session, "sprint", sprint["id"], "sprint_closed")
        assert len(rows) == 1
        assert _details(rows[0])["goal"] == "Close me"

    def test_no_sprint_closed_on_other_field_patch(self, client, db_session, make_sprint):
        sprint = make_sprint(sprint_number=1)
        client.patch(f"/api/sprints/{sprint['id']}", json={"goal": "new goal"})
        assert _events(db_session, "sprint", sprint["id"], "sprint_closed") == []


class TestConsolidationAckedEvent:
    def test_ack_emits_consolidation_acked(self, client, db_session, make_epic, make_sprint, make_agent):
        # No repo_path -> no over-ceiling check, naked ack passes.
        sprint = make_sprint(sprint_number=1)
        agent = make_agent(project_id=sprint["project_id"])
        r = client.post(
            f"/api/agents/{agent['id']}/consolidate-complete",
            json={"sprint_id": sprint["id"]},
            headers={"X-Agent-ID": str(agent["id"])},
        )
        assert r.status_code == 201, r.text
        rows = _events(db_session, "agent", agent["id"], "consolidation_acked")
        assert len(rows) == 1
        assert _details(rows[0]) == {"sprint_id": sprint["id"]}
        assert rows[0].project_id == sprint["project_id"]
        assert rows[0].agent_id == agent["id"]
