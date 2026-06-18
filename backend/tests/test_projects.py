# Path:          tests/test_projects.py
# File:          test_projects.py
# Created:       2026-03-28
# Purpose:       Full CRUD + filtering tests for /api/projects, including overhead + team
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/projects, POST /api/projects/:id/overhead,
#                GET /api/projects/:id/team (DWB-313, DWB-387)
# Data In:       Factory-created projects, tickets, test results via conftest fixtures
# Data Out:      Assertions on HTTP status codes, JSON shapes, and cascade deletes
# Last Modified: 2026-06-12

"""Tests for /api/projects CRUD and filtering."""

from datetime import datetime, timedelta

import pytest

from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType


class TestListProjects:
    def test_list_returns_200(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_project(self, client, make_project):
        project = make_project()
        projects = client.get("/api/projects").json()
        ids = [p["id"] for p in projects]
        assert project["id"] in ids

    def test_filter_by_status(self, client, make_project):
        make_project(status="active")
        make_project(status="paused")

        active = client.get("/api/projects", params={"status": "active"}).json()
        assert all(p["status"] == "active" for p in active)

        paused = client.get("/api/projects", params={"status": "paused"}).json()
        assert all(p["status"] == "paused" for p in paused)


class TestGetProject:
    def test_get_returns_200(self, client, make_project):
        project = make_project()
        r = client.get(f"/api/projects/{project['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == project["id"]

    def test_get_response_shape(self, client, make_project):
        project = make_project()
        data = client.get(f"/api/projects/{project['id']}").json()
        expected_keys = {
            "id", "prefix", "name", "description", "status", "repo_path",
            "jira_base_url", "jira_project_key",
            "tl_overhead_tokens", "pm_overhead_tokens",
            "tl_overhead_time_seconds", "pm_overhead_time_seconds",
            "force_headers", "force_test_coverage", "force_test_run",
            "force_initial_md", "force_architecture_md",
            "force_handoff_md", "force_consolidation",
            "playbooks_deployed_at",
            "created_at", "updated_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/projects/999999")
        assert r.status_code == 404


class TestCreateProject:
    def test_create_returns_201(self, client):
        r = client.post("/api/projects", json={
            "prefix": "NEW",
            "name": "New Project",
        })
        assert r.status_code == 201
        assert r.json()["prefix"] == "NEW"
        assert r.json()["name"] == "New Project"
        assert r.json()["status"] == "active"  # default

    def test_create_with_all_fields(self, client):
        r = client.post("/api/projects", json={
            "prefix": "FULL",
            "name": "Full Project",
            "description": "A described project",
            "status": "paused",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["description"] == "A described project"
        assert data["status"] == "paused"


class TestUpdateProject:
    def test_patch_updates_fields(self, client, make_project):
        project = make_project()
        r = client.patch(f"/api/projects/{project['id']}", json={
            "name": "Updated Name",
            "status": "paused",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "Updated Name"
        assert r.json()["status"] == "paused"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/projects/999999", json={"name": "Nope"})
        assert r.status_code == 404


class TestRepoPath:
    def test_create_with_repo_path(self, client):
        r = client.post("/api/projects", json={
            "prefix": "RPO",
            "name": "Repo Project",
            "repo_path": "/tmp/test-repo",
        })
        assert r.status_code == 201
        assert r.json()["repo_path"] == "/tmp/test-repo"

    def test_create_without_repo_path_defaults_null(self, client):
        r = client.post("/api/projects", json={
            "prefix": "NRP",
            "name": "No Repo Project",
        })
        assert r.status_code == 201
        assert r.json()["repo_path"] is None

    def test_patch_repo_path(self, client, make_project):
        project = make_project()
        r = client.patch(f"/api/projects/{project['id']}", json={
            "repo_path": "/tmp/updated-repo",
        })
        assert r.status_code == 200
        assert r.json()["repo_path"] == "/tmp/updated-repo"


class TestOverhead:
    def test_increment_tl_overhead(self, client, make_project):
        project = make_project()
        r = client.post(f"/api/projects/{project['id']}/overhead", json={
            "role": "team_lead",
            "tokens_used": 100,
            "time_spent_seconds": 30,
        })
        assert r.status_code == 200
        assert r.json()["tl_overhead_tokens"] == 100
        assert r.json()["tl_overhead_time_seconds"] == 30
        assert r.json()["pm_overhead_tokens"] == 0

    def test_increment_pm_overhead(self, client, make_project):
        project = make_project()
        r = client.post(f"/api/projects/{project['id']}/overhead", json={
            "role": "pm",
            "tokens_used": 200,
            "time_spent_seconds": 60,
        })
        assert r.status_code == 200
        assert r.json()["pm_overhead_tokens"] == 200
        assert r.json()["pm_overhead_time_seconds"] == 60
        assert r.json()["tl_overhead_tokens"] == 0

    def test_increment_accumulates(self, client, make_project):
        project = make_project()
        pid = project["id"]
        client.post(f"/api/projects/{pid}/overhead", json={
            "role": "team_lead", "tokens_used": 100,
        })
        r = client.post(f"/api/projects/{pid}/overhead", json={
            "role": "team_lead", "tokens_used": 50, "time_spent_seconds": 10,
        })
        assert r.status_code == 200
        assert r.json()["tl_overhead_tokens"] == 150
        assert r.json()["tl_overhead_time_seconds"] == 10

    def test_increment_invalid_role_returns_400(self, client, make_project):
        project = make_project()
        r = client.post(f"/api/projects/{project['id']}/overhead", json={
            "role": "developer", "tokens_used": 100,
        })
        assert r.status_code == 400

    def test_increment_nonexistent_project_returns_404(self, client):
        r = client.post("/api/projects/999999/overhead", json={
            "role": "team_lead", "tokens_used": 100,
        })
        assert r.status_code == 404


class TestDeleteProject:
    def test_delete_returns_204(self, client, make_project):
        project = make_project()
        r = client.delete(f"/api/projects/{project['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_project):
        project = make_project()
        client.delete(f"/api/projects/{project['id']}")
        r = client.get(f"/api/projects/{project['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/projects/999999")
        assert r.status_code == 404

    def test_delete_cascades_tickets(self, client, make_project, make_ticket):
        project = make_project()
        pid = project["id"]
        ticket = make_ticket(project_id=pid)
        client.delete(f"/api/projects/{pid}")
        r = client.get(f"/api/tickets/{ticket['id']}")
        assert r.status_code == 404

    def test_delete_cascades_test_results(self, client, make_project, make_test_result):
        project = make_project()
        pid = project["id"]
        tr = make_test_result(project_id=pid)
        client.delete(f"/api/projects/{pid}")
        r = client.get(f"/api/test-results/{tr['id']}")
        assert r.status_code == 404

    def test_delete_cascades_alerts(self, client, make_project, make_agent):
        project = make_project()
        pid = project["id"]
        agent = make_agent()
        alert = client.post("/api/alerts", json={
            "project_id": pid,
            "raised_by_agent_id": agent["id"],
            "title": "Test alert",
            "body": "Will be cascaded",
        })
        assert alert.status_code == 201
        alert_id = alert.json()["id"]
        client.delete(f"/api/projects/{pid}")
        r = client.get(f"/api/alerts/{alert_id}")
        assert r.status_code == 404


class TestProjectTeam:
    """DWB-313 — GET /api/projects/{id}/team single-roundtrip team listing."""

    def _assign(self, client, project_id, agent_id):
        r = client.post("/api/project-agents", json={
            "project_id": project_id, "agent_id": agent_id,
        })
        assert r.status_code == 201

    def test_team_missing_project_returns_404(self, client):
        r = client.get("/api/projects/999999/team")
        assert r.status_code == 404

    def test_team_empty_project_returns_zero_agents(self, client, make_project):
        project = make_project()
        r = client.get(f"/api/projects/{project['id']}/team")
        assert r.status_code == 200
        body = r.json()
        assert body["project_id"] == project["id"]
        assert body["project_prefix"] == project["prefix"]
        assert body["agents"] == []

    def test_team_returns_member_shape(self, client, make_project, make_agent):
        project = make_project()
        agent = make_agent(
            project_id=project["id"], name="Archie", role="team-lead",
            api_key="team-archie-1",
        )
        self._assign(client, project["id"], agent["id"])

        r = client.get(f"/api/projects/{project['id']}/team")
        assert r.status_code == 200
        body = r.json()
        assert len(body["agents"]) == 1
        member = body["agents"][0]
        # Shape contract: exactly these keys, no more
        assert set(member.keys()) == {
            "agent_id", "name", "role", "is_active", "assigned_at",
            "last_seen", "presumed_live",
        }
        assert member["agent_id"] == agent["id"]
        assert member["name"] == "Archie"
        assert member["role"] == "team-lead"
        assert member["is_active"] is True
        # DWB-387: no hook_sessions yet → last_seen None, presumed_live False
        assert member["last_seen"] is None
        assert member["presumed_live"] is False

    def test_team_default_excludes_inactive_agents(
        self, client, make_project, make_agent,
    ):
        """Default filter is is_active=true. Inactive agents must NOT appear."""
        project = make_project()
        pid = project["id"]

        # 3 active + 1 inactive
        active_names = ["Archie", "Devin", "Pixel"]
        active_agents = []
        for i, name in enumerate(active_names):
            a = make_agent(
                project_id=pid, name=name, role="developer",
                api_key=f"team-active-{i}",
            )
            active_agents.append(a)
            self._assign(client, pid, a["id"])

        inactive = make_agent(
            project_id=pid, name="Retired", role="developer",
            api_key="team-inactive", is_active=False,
        )
        self._assign(client, pid, inactive["id"])

        r = client.get(f"/api/projects/{pid}/team")
        assert r.status_code == 200
        body = r.json()
        names = {a["name"] for a in body["agents"]}
        assert names == set(active_names), (
            f"default team listing should only return active agents; got {names}"
        )
        assert all(a["is_active"] for a in body["agents"])

    def test_team_include_inactive_returns_all(
        self, client, make_project, make_agent,
    ):
        """?include_inactive=true returns the full historical roster."""
        project = make_project()
        pid = project["id"]

        active = make_agent(
            project_id=pid, name="Working", role="developer",
            api_key="team-incl-active",
        )
        inactive = make_agent(
            project_id=pid, name="Retired", role="developer",
            api_key="team-incl-inactive", is_active=False,
        )
        self._assign(client, pid, active["id"])
        self._assign(client, pid, inactive["id"])

        r = client.get(
            f"/api/projects/{pid}/team", params={"include_inactive": "true"}
        )
        assert r.status_code == 200
        body = r.json()
        names = {a["name"] for a in body["agents"]}
        assert names == {"Working", "Retired"}
        # Confirm the inactive row carries is_active=False so callers can render it
        retired = next(a for a in body["agents"] if a["name"] == "Retired")
        assert retired["is_active"] is False

    def test_team_does_not_include_agents_from_other_projects(
        self, client, make_project, make_agent,
    ):
        """Sanity: project_id filter must isolate per-project rosters."""
        proj_a = make_project()
        proj_b = make_project()

        agent_a = make_agent(
            project_id=proj_a["id"], name="A-only", role="developer",
            api_key="iso-a",
        )
        agent_b = make_agent(
            project_id=proj_b["id"], name="B-only", role="developer",
            api_key="iso-b",
        )
        self._assign(client, proj_a["id"], agent_a["id"])
        self._assign(client, proj_b["id"], agent_b["id"])

        body_a = client.get(f"/api/projects/{proj_a['id']}/team").json()
        names_a = {m["name"] for m in body_a["agents"]}
        assert names_a == {"A-only"}
        assert "B-only" not in names_a


class TestProjectTeamLiveness:
    """DWB-387 — last_seen + presumed_live on GET /api/projects/{id}/team."""

    def _assign(self, client, project_id, agent_id):
        r = client.post(
            "/api/project-agents",
            json={"project_id": project_id, "agent_id": agent_id},
        )
        assert r.status_code == 201

    def _insert_hook(
        self, db_session, project_id, agent_id, *, session_id,
        start_offset_minutes, end_offset_minutes=None,
    ):
        now = datetime.utcnow()
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            agent_id=agent_id,
            start_time=now - timedelta(minutes=start_offset_minutes),
            end_time=(
                None
                if end_offset_minutes is None
                else now - timedelta(minutes=end_offset_minutes)
            ),
            status=(
                HookSessionStatus.completed
                if end_offset_minutes is not None
                else HookSessionStatus.active
            ),
            session_type=HookSessionType.teammate,
        )
        db_session.add(row)
        db_session.flush()
        return row

    def test_recent_hook_session_marks_presumed_live(
        self, client, db_session, make_project, make_agent,
    ):
        project = make_project()
        agent = make_agent(
            project_id=project["id"], name="Active", role="developer",
            api_key="live-1",
        )
        self._assign(client, project["id"], agent["id"])
        # Active session that started 3 min ago, still running (no end_time).
        self._insert_hook(
            db_session, project["id"], agent["id"],
            session_id="live-sess-1", start_offset_minutes=3,
        )

        body = client.get(f"/api/projects/{project['id']}/team").json()
        member = next(a for a in body["agents"] if a["agent_id"] == agent["id"])
        assert member["last_seen"] is not None
        assert member["presumed_live"] is True

    def test_old_hook_session_marks_presumed_dead(
        self, client, db_session, make_project, make_agent,
    ):
        project = make_project()
        agent = make_agent(
            project_id=project["id"], name="Stale", role="developer",
            api_key="live-2",
        )
        self._assign(client, project["id"], agent["id"])
        # Completed session that ended 45 min ago — well beyond the 15-min window.
        self._insert_hook(
            db_session, project["id"], agent["id"],
            session_id="stale-sess-1",
            start_offset_minutes=60, end_offset_minutes=45,
        )

        body = client.get(f"/api/projects/{project['id']}/team").json()
        member = next(a for a in body["agents"] if a["agent_id"] == agent["id"])
        assert member["last_seen"] is not None
        assert member["presumed_live"] is False

    def test_last_seen_picks_most_recent_event_across_sessions(
        self, client, db_session, make_project, make_agent,
    ):
        """An agent with both old and recent sessions reports the recent one."""
        project = make_project()
        agent = make_agent(
            project_id=project["id"], name="Multi", role="developer",
            api_key="live-3",
        )
        self._assign(client, project["id"], agent["id"])
        # Old session (started 6h ago, ended 5h ago)
        self._insert_hook(
            db_session, project["id"], agent["id"],
            session_id="multi-old",
            start_offset_minutes=360, end_offset_minutes=300,
        )
        # Recent session (still active, started 2 min ago)
        self._insert_hook(
            db_session, project["id"], agent["id"],
            session_id="multi-fresh", start_offset_minutes=2,
        )

        body = client.get(f"/api/projects/{project['id']}/team").json()
        member = next(a for a in body["agents"] if a["agent_id"] == agent["id"])
        assert member["presumed_live"] is True
        # last_seen must reflect the fresh session, not the 6h-old one.
        last_seen = datetime.fromisoformat(member["last_seen"])
        assert (datetime.utcnow() - last_seen).total_seconds() < 10 * 60

    def test_hook_session_for_other_agent_does_not_leak(
        self, client, db_session, make_project, make_agent,
    ):
        """An agent without their own hook_sessions stays offline even when a
        teammate on the same project has activity."""
        project = make_project()
        active_agent = make_agent(
            project_id=project["id"], name="Worker", role="developer",
            api_key="live-4a",
        )
        idle_agent = make_agent(
            project_id=project["id"], name="Idle", role="developer",
            api_key="live-4b",
        )
        self._assign(client, project["id"], active_agent["id"])
        self._assign(client, project["id"], idle_agent["id"])
        self._insert_hook(
            db_session, project["id"], active_agent["id"],
            session_id="iso-active", start_offset_minutes=2,
        )

        body = client.get(f"/api/projects/{project['id']}/team").json()
        worker = next(
            a for a in body["agents"] if a["agent_id"] == active_agent["id"]
        )
        idle = next(
            a for a in body["agents"] if a["agent_id"] == idle_agent["id"]
        )
        assert worker["presumed_live"] is True
        assert idle["last_seen"] is None
        assert idle["presumed_live"] is False

    def test_inactive_agent_still_carries_liveness_fields(
        self, client, db_session, make_project, make_agent,
    ):
        """include_inactive=true returns liveness fields for inactive agents too.

        The is_active filter applies to Agent rows; the hook_sessions LEFT JOIN
        is independent. An inactive agent that had recent activity should still
        surface last_seen + presumed_live (TL ask: don't filter liveness data by
        agent activeness — the caller decides what to do with it).
        """
        project = make_project()
        retired = make_agent(
            project_id=project["id"], name="Retired", role="developer",
            api_key="inact-1", is_active=False,
        )
        self._assign(client, project["id"], retired["id"])
        self._insert_hook(
            db_session, project["id"], retired["id"],
            session_id="retired-recent", start_offset_minutes=4,
        )

        body = client.get(
            f"/api/projects/{project['id']}/team",
            params={"include_inactive": "true"},
        ).json()
        member = next(a for a in body["agents"] if a["agent_id"] == retired["id"])
        assert member["is_active"] is False
        assert member["last_seen"] is not None
        assert member["presumed_live"] is True
