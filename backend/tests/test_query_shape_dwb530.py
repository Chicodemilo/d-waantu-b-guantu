# Path: tests/test_query_shape_dwb530.py
# File: test_query_shape_dwb530.py
# Created: 2026-09-15
# Purpose: DWB-530 - wrong query/path shapes on the sessions + tl-channel read endpoints return 400 naming the valid params; a genuinely missing row 404s naming the entity; valid shapes are unchanged.
# Caller: pytest
# Callees: /api/sessions, /api/projects/{id}/sessions, /api/tl-channel, app.services.query_shape
# Data In: pytest fixtures (client, make_project, make_agent)
# Data Out: assertions
# Last Modified: 2026-09-15

from fastapi import HTTPException
from starlette.requests import Request

from app.services import query_shape


def _tl(make_agent, **overrides):
    overrides.setdefault("role", "team-lead")
    return make_agent(**overrides)


def _request(query: str) -> Request:
    scope = {
        "type": "http", "method": "GET", "path": "/x",
        "query_string": query.encode(), "headers": [],
    }
    return Request(scope)


class TestQueryShapeService:
    def test_known_params_pass(self):
        query_shape.reject_unknown_query_params(
            _request("limit=5&offset=1"), {"limit", "offset"}, endpoint="GET /x"
        )

    def test_unknown_param_400_names_offender_and_valid(self):
        try:
            query_shape.reject_unknown_query_params(
                _request("limit=5&status=open&project_id=1"),
                {"limit", "offset"}, endpoint="GET /x",
            )
        except HTTPException as e:
            assert e.status_code == 400
            assert "GET /x" in e.detail
            assert "project_id" in e.detail and "status" in e.detail
            assert "valid params: limit, offset" in e.detail
        else:
            raise AssertionError("expected 400")

    def test_collection_form_helper_names_alternatives(self):
        exc = query_shape.collection_form_not_available(
            "GET /api/things", use=["GET /api/a", "GET /api/b"]
        )
        assert exc.status_code == 400
        assert "GET /api/things has no collection form" in exc.detail
        assert "GET /api/a" in exc.detail and "GET /api/b" in exc.detail


class TestSessionsWrongShape:
    """Repro 1: GET /api/sessions?project_id=X&status=open used to be a bare
    404 that read as 'no open session'."""

    def test_sessions_collection_query_is_400_naming_routes(self, client, make_project):
        project = make_project()
        r = client.get(f"/api/sessions?project_id={project['id']}&status=open")
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail != "Not Found"
        assert "GET /api/sessions has no collection form" in detail
        assert "/api/projects/{project_id}/sessions" in detail
        assert "limit" in detail and "offset" in detail
        assert "/api/sessions/{session_id}" in detail

    def test_sessions_bare_collection_is_400_too(self, client):
        r = client.get("/api/sessions")
        assert r.status_code == 400
        assert "has no collection form" in r.json()["detail"]

    def test_project_sessions_unknown_filter_400_names_valid_params(
        self, client, make_project
    ):
        project = make_project()
        r = client.get(f"/api/projects/{project['id']}/sessions?status=open")
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "status" in detail
        assert "valid params: limit, offset" in detail

    def test_project_sessions_valid_params_still_200_empty(self, client, make_project):
        project = make_project()
        r = client.get(f"/api/projects/{project['id']}/sessions?limit=5&offset=0")
        assert r.status_code == 200
        assert r.json() == []

    def test_project_sessions_missing_project_404_names_entity(self, client):
        r = client.get("/api/projects/999999999/sessions")
        assert r.status_code == 404
        assert "Project 999999999 not found" == r.json()["detail"]

    def test_session_detail_missing_row_404_names_entity(self, client):
        r = client.get("/api/sessions/999999999")
        assert r.status_code == 404
        assert r.json()["detail"] == "DWB session 999999999 not found"

    def test_session_detail_non_int_id_is_422_not_404(self, client):
        r = client.get("/api/sessions/open")
        assert r.status_code == 422


class TestTlChannelWrongShape:
    """Repro 2: GET /api/tl-channel/156 used to be a bare 404 - no way to tell
    'no such route' from 'no such row'."""

    def test_get_message_missing_row_404_names_entity(self, client):
        r = client.get("/api/tl-channel/999999999")
        assert r.status_code == 404
        assert r.json()["detail"] == "tl-channel message 999999999 not found"

    def test_get_message_by_id_200(self, client, make_agent):
        sender = _tl(make_agent)
        target = _tl(make_agent)
        sent = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "to_agent_id": target["id"],
            "body": "fetch me by id",
        })
        assert sent.status_code == 201, sent.text
        mid = sent.json()["id"]
        r = client.get(f"/api/tl-channel/{mid}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["id"] == mid
        assert data["body"] == "fetch me by id"
        assert data["to_agent_id"] == target["id"]
        assert data["read_by"] == []

    def test_get_message_is_pointer_target_of_ping_alert(
        self, client, db_session, make_agent
    ):
        """DWB-528 + DWB-530: the 'full message: tl-channel #<id>' pointer in a
        ping alert resolves through GET /api/tl-channel/{id}."""
        import re
        from app.models.alert import Alert
        sender = _tl(make_agent)
        target = _tl(make_agent)
        long_body = "z" * 400
        sent = client.post("/api/tl-channel", json={
            "from_agent_id": sender["id"],
            "to_agent_id": target["id"],
            "body": long_body,
        })
        assert sent.status_code == 201
        alert = db_session.query(Alert).filter(
            Alert.recipient_agent_id == target["id"]
        ).one()
        m = re.search(r"tl-channel #(\d+)", alert.body)
        assert m, alert.body
        r = client.get(f"/api/tl-channel/{m.group(1)}")
        assert r.status_code == 200
        assert r.json()["body"] == long_body

    def test_get_message_non_int_id_is_422(self, client):
        r = client.get("/api/tl-channel/abc")
        assert r.status_code == 422

    def test_list_unknown_param_400_names_valid(self, client):
        r = client.get("/api/tl-channel?project_id=1")
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "project_id" in detail
        assert "valid params: limit" in detail

    def test_list_valid_limit_still_200(self, client):
        r = client.get("/api/tl-channel?limit=5")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_unread_unknown_param_400_names_valid(self, client, make_agent):
        tl = _tl(make_agent)
        r = client.get(f"/api/tl-channel/unread?agent_id={tl['id']}&project_id=1")
        assert r.status_code == 400, r.text
        assert "valid params: agent_id" in r.json()["detail"]

    def test_unread_valid_still_200_and_static_route_wins_over_id(
        self, client, make_agent
    ):
        tl = _tl(make_agent)
        r = client.get(f"/api/tl-channel/unread?agent_id={tl['id']}")
        assert r.status_code == 200
        assert r.json() == []

    def test_unread_missing_agent_404_names_entity(self, client):
        r = client.get("/api/tl-channel/unread?agent_id=999999999")
        assert r.status_code == 404
        assert "Agent not found" in r.json()["detail"]
