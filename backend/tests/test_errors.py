# Path: tests/test_errors.py
# File: test_errors.py
# Created: 2026-04-09
# Purpose: Tests for error logging endpoints and auto-logging behavior
# Caller: pytest
# Callees: app/routers/errors.py, app/models/error_log.py
# Data In: Test fixtures
# Data Out: Assertions
# Last Modified: 2026-04-09

import pytest


class TestCreateErrorLog:
    def test_post_returns_201(self, client):
        r = client.post("/api/errors", json={"message": "something broke"})
        assert r.status_code == 201

    def test_post_response_shape(self, client):
        r = client.post("/api/errors", json={
            "message": "test error",
            "source": "frontend",
            "endpoint": "GET /api/tickets",
            "status_code": 500,
        })
        data = r.json()
        assert data["message"] == "test error"
        assert data["source"] == "frontend"
        assert data["endpoint"] == "GET /api/tickets"
        assert data["status_code"] == 500
        assert data["id"] is not None
        assert data["created_at"] is not None

    def test_post_with_stack_trace(self, client):
        r = client.post("/api/errors", json={
            "message": "TypeError: x is not a function",
            "source": "frontend",
            "stack_trace": "TypeError: x is not a function\n  at App.jsx:42\n  at render",
            "file_path": "App.jsx",
            "function_name": "render",
            "line_number": 42,
        })
        data = r.json()
        assert data["stack_trace"] is not None
        assert data["file_path"] == "App.jsx"
        assert data["function_name"] == "render"
        assert data["line_number"] == 42

    def test_post_with_project_id(self, client, make_project):
        project = make_project()
        r = client.post("/api/errors", json={
            "message": "project-scoped error",
            "project_id": project["id"],
        })
        assert r.status_code == 201
        assert r.json()["project_id"] == project["id"]

    def test_post_backend_source(self, client):
        r = client.post("/api/errors", json={
            "message": "division by zero",
            "source": "backend",
            "error_type": "ZeroDivisionError",
        })
        data = r.json()
        assert data["source"] == "backend"
        assert data["error_type"] == "ZeroDivisionError"

    def test_post_hook_source(self, client):
        r = client.post("/api/errors", json={
            "message": "hook timeout",
            "source": "hook",
        })
        assert r.json()["source"] == "hook"

    def test_defaults_to_frontend(self, client):
        r = client.post("/api/errors", json={"message": "oops"})
        assert r.json()["source"] == "frontend"

    def test_nullable_fields_default_to_none(self, client):
        r = client.post("/api/errors", json={"message": "minimal"})
        data = r.json()
        assert data["project_id"] is None
        assert data["agent_id"] is None
        assert data["endpoint"] is None
        assert data["error_type"] is None
        assert data["stack_trace"] is None
        assert data["file_path"] is None
        assert data["function_name"] is None
        assert data["line_number"] is None
        assert data["status_code"] is None


class TestListErrorLogs:
    def test_list_returns_200(self, client):
        r = client.get("/api/errors")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_returns_posted_errors(self, client):
        client.post("/api/errors", json={"message": "err1"})
        client.post("/api/errors", json={"message": "err2"})
        r = client.get("/api/errors")
        messages = [e["message"] for e in r.json()]
        assert "err1" in messages
        assert "err2" in messages

    def test_filter_by_project_id(self, client, make_project):
        p1 = make_project()
        p2 = make_project()
        client.post("/api/errors", json={"message": "p1 err", "project_id": p1["id"]})
        client.post("/api/errors", json={"message": "p2 err", "project_id": p2["id"]})
        r = client.get(f"/api/errors?project_id={p1['id']}")
        errors = r.json()
        assert all(e["project_id"] == p1["id"] for e in errors)

    def test_filter_by_source(self, client):
        client.post("/api/errors", json={"message": "be err", "source": "backend"})
        client.post("/api/errors", json={"message": "fe err", "source": "frontend"})
        r = client.get("/api/errors?source=backend")
        errors = r.json()
        assert all(e["source"] == "backend" for e in errors)

    def test_list_ordered_newest_first(self, client):
        client.post("/api/errors", json={"message": "first"})
        client.post("/api/errors", json={"message": "second"})
        r = client.get("/api/errors")
        errors = r.json()
        if len(errors) >= 2:
            assert errors[0]["created_at"] >= errors[1]["created_at"]

    def test_limit_parameter(self, client):
        for i in range(5):
            client.post("/api/errors", json={"message": f"err {i}"})
        r = client.get("/api/errors?limit=2")
        assert len(r.json()) <= 2


class TestStackTraceParsing:
    """Verify the middleware parses Python tracebacks to extract file/function/line."""

    def test_parse_app_frame(self):
        from app.middleware.error_logger import _extract_origin
        tb = '''Traceback (most recent call last):
  File "/Users/dev/backend/app/routers/tickets.py", line 45, in create_ticket
    raise ValueError("bad input")
ValueError: bad input'''
        file_path, func, line = _extract_origin(tb)
        assert file_path == "/Users/dev/backend/app/routers/tickets.py"
        assert func == "create_ticket"
        assert line == 45

    def test_prefers_deepest_app_frame(self):
        from app.middleware.error_logger import _extract_origin
        tb = '''Traceback (most recent call last):
  File "/Users/dev/backend/app/routers/projects.py", line 10, in list_projects
    result = svc.get_projects(db)
  File "/Users/dev/backend/app/services/project.py", line 22, in get_projects
    raise RuntimeError("db fail")
RuntimeError: db fail'''
        file_path, func, line = _extract_origin(tb)
        assert file_path == "/Users/dev/backend/app/services/project.py"
        assert func == "get_projects"
        assert line == 22

    def test_ignores_library_frames(self):
        from app.middleware.error_logger import _extract_origin
        tb = '''Traceback (most recent call last):
  File "/lib/python3.12/site-packages/starlette/routing.py", line 66, in app
    response = await func(request)
  File "/Users/dev/backend/app/routers/alerts.py", line 30, in create_alert
    raise ValueError("missing field")
  File "/lib/python3.12/site-packages/sqlalchemy/orm/session.py", line 100, in commit
    self.commit()
ValueError: missing field'''
        file_path, func, line = _extract_origin(tb)
        assert file_path == "/Users/dev/backend/app/routers/alerts.py"
        assert func == "create_alert"
        assert line == 30

    def test_returns_none_for_no_app_frames(self):
        from app.middleware.error_logger import _extract_origin
        tb = '''Traceback (most recent call last):
  File "/lib/python3.12/threading.py", line 100, in run
    self._target()
RuntimeError: oops'''
        file_path, func, line = _extract_origin(tb)
        assert file_path is None
        assert func is None
        assert line is None

    def test_extract_project_id_from_path(self):
        from app.middleware.error_logger import _extract_project_id
        assert _extract_project_id("/api/projects/5/scan-tokens") == 5
        assert _extract_project_id("/api/projects/123/deploy-playbooks") == 123
        assert _extract_project_id("/api/tickets") is None
        assert _extract_project_id("/api/agents/4") is None
