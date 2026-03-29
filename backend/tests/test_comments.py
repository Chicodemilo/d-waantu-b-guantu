# Path:          tests/test_comments.py
# File:          test_comments.py
# Created:       2026-03-28
# Purpose:       CRUD + filtering tests for /api/comments
# Caller:        pytest
# Callees:       GET/POST/DELETE /api/comments, GET /api/comments/:id
# Data In:       Factory-created tickets, agents via conftest fixtures
# Data Out:      Assertions on HTTP status codes and JSON response shapes
# Last Modified: 2026-03-29

"""Tests for /api/comments endpoints."""


class TestListComments:
    def test_list_returns_200(self, client):
        r = client.get("/api/comments")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_contains_created_comment(self, client, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent()
        created = client.post("/api/comments", json={
            "ticket_id": ticket["id"],
            "author_agent_id": agent["id"],
            "body": "Test comment",
        }).json()
        comments = client.get("/api/comments").json()
        ids = [c["id"] for c in comments]
        assert created["id"] in ids

    def test_filter_by_ticket_id(self, client, make_ticket, make_agent):
        t1 = make_ticket()
        t2 = make_ticket()
        agent = make_agent()
        client.post("/api/comments", json={
            "ticket_id": t1["id"], "author_agent_id": agent["id"], "body": "On t1",
        })
        client.post("/api/comments", json={
            "ticket_id": t2["id"], "author_agent_id": agent["id"], "body": "On t2",
        })
        comments = client.get("/api/comments", params={"ticket_id": t1["id"]}).json()
        assert len(comments) >= 1
        assert all(c["ticket_id"] == t1["id"] for c in comments)

    def test_filter_by_author_agent_id(self, client, make_ticket, make_agent):
        ticket = make_ticket()
        a1 = make_agent()
        a2 = make_agent()
        client.post("/api/comments", json={
            "ticket_id": ticket["id"], "author_agent_id": a1["id"], "body": "By a1",
        })
        client.post("/api/comments", json={
            "ticket_id": ticket["id"], "author_agent_id": a2["id"], "body": "By a2",
        })
        comments = client.get("/api/comments", params={"author_agent_id": a1["id"]}).json()
        assert all(c["author_agent_id"] == a1["id"] for c in comments)


class TestGetComment:
    def test_get_returns_200(self, client, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent()
        created = client.post("/api/comments", json={
            "ticket_id": ticket["id"],
            "author_agent_id": agent["id"],
            "body": "A comment",
        }).json()
        r = client.get(f"/api/comments/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_response_shape(self, client, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent()
        created = client.post("/api/comments", json={
            "ticket_id": ticket["id"],
            "author_agent_id": agent["id"],
            "body": "Shape test",
        }).json()
        data = client.get(f"/api/comments/{created['id']}").json()
        expected_keys = {"id", "ticket_id", "author_agent_id", "body", "created_at"}
        assert set(data.keys()) == expected_keys

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/comments/999999")
        assert r.status_code == 404


class TestCreateComment:
    def test_create_returns_201(self, client, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent()
        r = client.post("/api/comments", json={
            "ticket_id": ticket["id"],
            "author_agent_id": agent["id"],
            "body": "New comment",
        })
        assert r.status_code == 201
        assert r.json()["body"] == "New comment"
        assert r.json()["ticket_id"] == ticket["id"]
        assert r.json()["author_agent_id"] == agent["id"]


class TestDeleteComment:
    def test_delete_returns_204(self, client, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent()
        created = client.post("/api/comments", json={
            "ticket_id": ticket["id"],
            "author_agent_id": agent["id"],
            "body": "To delete",
        }).json()
        r = client.delete(f"/api/comments/{created['id']}")
        assert r.status_code == 204

    def test_get_after_delete_returns_404(self, client, make_ticket, make_agent):
        ticket = make_ticket()
        agent = make_agent()
        created = client.post("/api/comments", json={
            "ticket_id": ticket["id"],
            "author_agent_id": agent["id"],
            "body": "Will be deleted",
        }).json()
        client.delete(f"/api/comments/{created['id']}")
        r = client.get(f"/api/comments/{created['id']}")
        assert r.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/comments/999999")
        assert r.status_code == 404
