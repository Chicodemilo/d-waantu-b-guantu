# Path:          tests/test_tickets.py
# File:          test_tickets.py
# Created:       2026-03-28
# Purpose:       Full CRUD + filtering tests for /api/tickets
# Caller:        pytest
# Callees:       GET/POST/PATCH/DELETE /api/tickets, POST /api/tickets/:id/tokens
# Data In:       Factory-created projects, sprints, agents via conftest fixtures
# Data Out:      Assertions on HTTP status codes, JSON shapes, and token increments
# Last Modified: 2026-03-29

"""Tests for /api/tickets CRUD and filtering."""

import pytest


class TestListTickets:
    def test_list_returns_200(self, client):
        r = client.get("/api/tickets")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_filter_by_project_id(self, client, make_project, make_ticket):
        p1 = make_project()
        p2 = make_project()
        t1 = make_ticket(project_id=p1["id"])
        t2 = make_ticket(project_id=p2["id"])

        filtered = client.get("/api/tickets", params={"project_id": p1["id"]}).json()
        ids = [t["id"] for t in filtered]
        assert t1["id"] in ids
        assert t2["id"] not in ids

    def test_filter_by_status(self, client, make_ticket):
        make_ticket(status="todo")
        make_ticket(status="in_progress")

        todo = client.get("/api/tickets", params={"status": "todo"}).json()
        assert all(t["status"] == "todo" for t in todo)

    def test_filter_by_ticket_type(self, client, make_ticket):
        make_ticket(ticket_type="bug")
        make_ticket(ticket_type="story")

        bugs = client.get("/api/tickets", params={"ticket_type": "bug"}).json()
        assert all(t["ticket_type"] == "bug" for t in bugs)


class TestGetTicket:
    def test_get_returns_200(self, client, make_ticket):
        ticket = make_ticket()
        r = client.get(f"/api/tickets/{ticket['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == ticket["id"]

    def test_get_response_shape(self, client, make_ticket):
        ticket = make_ticket()
        data = client.get(f"/api/tickets/{ticket['id']}").json()
        expected_keys = {
            "id", "project_id", "epic_id", "sprint_id", "assigned_agent_id",
            "ticket_number", "ticket_key", "title", "description",
            "ticket_type", "status", "tokens_used", "time_spent_seconds",
            "token_source", "jira_issue_key",
            "created_at", "updated_at", "completed_at",
        }
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/tickets/999999")
        assert r.status_code == 404


class TestCreateTicket:
    def test_create_returns_201(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = client.post("/api/tickets", json={
            "project_id": project["id"],
            "ticket_number": 1,
            "ticket_key": "CRT-001",
            "title": "Created ticket",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "Created ticket"
        assert data["status"] == "backlog"  # default
        assert data["ticket_type"] == "task"  # default

    def test_create_with_all_fields(self, client, make_project, make_sprint):
        project = make_project()
        make_sprint(project_id=project["id"])
        r = client.post("/api/tickets", json={
            "project_id": project["id"],
            "ticket_number": 2,
            "ticket_key": "CRT-002",
            "title": "Full ticket",
            "description": "Detailed desc",
            "ticket_type": "bug",
            "status": "todo",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["ticket_type"] == "bug"
        assert data["status"] == "todo"
        assert data["description"] == "Detailed desc"


class TestUpdateTicket:
    def test_patch_updates_fields(self, client, make_ticket):
        ticket = make_ticket()
        r = client.patch(f"/api/tickets/{ticket['id']}", json={
            "title": "Updated Title",
            "status": "in_progress",
        })
        assert r.status_code == 200
        assert r.json()["title"] == "Updated Title"
        assert r.json()["status"] == "in_progress"

    def test_patch_nonexistent_returns_404(self, client):
        r = client.patch("/api/tickets/999999", json={"title": "Nope"})
        assert r.status_code == 404


class TestDeleteTicket:
    def test_delete_returns_204(self, client, make_ticket):
        ticket = make_ticket()
        r = client.delete(f"/api/tickets/{ticket['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_ticket):
        ticket = make_ticket()
        client.delete(f"/api/tickets/{ticket['id']}")
        r = client.get(f"/api/tickets/{ticket['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/tickets/999999")
        assert r.status_code == 404
