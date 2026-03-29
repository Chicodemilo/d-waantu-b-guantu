# Path:          tests/test_agent_id_resolution.py
# File:          test_agent_id_resolution.py
# Created:       2026-03-29
# Purpose:       Tests for X-Agent-ID header attribution and fallback chain
# Caller:        pytest
# Callees:       app.middleware.activity_logger._resolve_agent_id
# Data In:       Factory-created projects, agents, project-agents via conftest fixtures
# Data Out:      Assertions on agent_id resolution priority
# Last Modified: 2026-03-29

"""Tests for X-Agent-ID header resolution in activity logger middleware."""

from unittest.mock import MagicMock

from app.middleware.activity_logger import _resolve_agent_id, _parse_entity_type


def _fake_request(headers=None):
    """Create a mock Starlette Request with optional headers."""
    req = MagicMock()
    req.headers = headers or {}
    return req


class TestXAgentIDHeader:
    """X-Agent-ID header should be highest priority for agent attribution."""

    def test_header_sets_agent_id(self, db_session):
        request = _fake_request(headers={"X-Agent-ID": "42"})
        result = _resolve_agent_id(request, {}, "ticket", 1, db_session)
        assert result == 42

    def test_header_overrides_body_fields(self, db_session):
        request = _fake_request(headers={"X-Agent-ID": "99"})
        data = {"assigned_agent_id": 10, "agent_id": 20}
        result = _resolve_agent_id(request, data, "ticket", 1, db_session)
        assert result == 99

    def test_header_overrides_raised_by_agent_id(self, db_session):
        request = _fake_request(headers={"X-Agent-ID": "55"})
        data = {"raised_by_agent_id": 77}
        result = _resolve_agent_id(request, data, "alert", 1, db_session)
        assert result == 55

    def test_invalid_header_falls_through(self, db_session):
        request = _fake_request(headers={"X-Agent-ID": "not-a-number"})
        data = {"assigned_agent_id": 10}
        result = _resolve_agent_id(request, data, "ticket", 1, db_session)
        assert result == 10

    def test_empty_header_falls_through(self, db_session):
        request = _fake_request(headers={"X-Agent-ID": ""})
        data = {"agent_id": 5}
        result = _resolve_agent_id(request, data, "ticket", 1, db_session)
        assert result == 5


class TestFallbackChain:
    """Without X-Agent-ID header, resolution follows entity-type-aware fallback."""

    def test_ticket_uses_assigned_agent_id(self, db_session):
        request = _fake_request()
        data = {"assigned_agent_id": 10, "agent_id": 20}
        result = _resolve_agent_id(request, data, "ticket", 1, db_session)
        assert result == 10

    def test_alert_uses_raised_by_agent_id(self, db_session):
        request = _fake_request()
        data = {"raised_by_agent_id": 30, "agent_id": 40}
        result = _resolve_agent_id(request, data, "alert", 1, db_session)
        assert result == 30

    def test_generic_entity_uses_assigned_agent_id_first(self, db_session):
        request = _fake_request()
        data = {"assigned_agent_id": 1, "agent_id": 2, "raised_by_agent_id": 3}
        result = _resolve_agent_id(request, data, "comment", 1, db_session)
        assert result == 1

    def test_generic_entity_falls_to_agent_id(self, db_session):
        request = _fake_request()
        data = {"agent_id": 7}
        result = _resolve_agent_id(request, data, "comment", 1, db_session)
        assert result == 7

    def test_generic_entity_falls_to_raised_by(self, db_session):
        request = _fake_request()
        data = {"raised_by_agent_id": 9}
        result = _resolve_agent_id(request, data, "comment", 1, db_session)
        assert result == 9

    def test_no_fields_returns_none(self, db_session):
        request = _fake_request()
        result = _resolve_agent_id(request, {}, "comment", 1, db_session)
        assert result is None

    def test_sprint_with_pm_fallback(
        self, client, make_project, make_agent, make_project_agent, db_session
    ):
        """Sprint/epic creation falls back to project PM when no body fields."""
        project = make_project()
        pm = make_agent(role="pm", name="PM Agent")
        make_project_agent(project_id=project["id"], agent_id=pm["id"])

        request = _fake_request()
        result = _resolve_agent_id(request, {}, "sprint", project["id"], db_session)
        assert result == pm["id"]

    def test_sprint_without_pm_returns_none(self, db_session, client, make_project):
        """Sprint creation with no PM assigned returns None."""
        project = make_project()
        request = _fake_request()
        result = _resolve_agent_id(request, {}, "sprint", project["id"], db_session)
        assert result is None


class TestParseEntityType:
    """URL path → entity type parsing."""

    def test_tickets_path(self):
        assert _parse_entity_type("/api/tickets/5") == "ticket"

    def test_sprints_path(self):
        assert _parse_entity_type("/api/sprints") == "sprint"

    def test_activity_logs_hyphen(self):
        assert _parse_entity_type("/api/activity-logs") == "activity_log"

    def test_non_api_path_returns_none(self):
        assert _parse_entity_type("/health") is None
