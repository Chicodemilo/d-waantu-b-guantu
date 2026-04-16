# Path:          tests/test_projects.py
# File:          test_projects.py
# Created:       2026-03-28
# Purpose:       Full CRUD + filtering tests for /api/projects, including overhead
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/projects, POST /api/projects/:id/overhead
# Data In:       Factory-created projects, tickets, test results via conftest fixtures
# Data Out:      Assertions on HTTP status codes, JSON shapes, and cascade deletes
# Last Modified: 2026-04-16

"""Tests for /api/projects CRUD and filtering."""

import pytest


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
            "force_initial_md", "force_architecture_md", "force_team_md",
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
