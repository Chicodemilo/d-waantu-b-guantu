# Path: tests/test_agent_marker_endpoint.py
# File: test_agent_marker_endpoint.py
# Created: 2026-06-05
# Purpose: Tests for POST /api/agents/{id}/marker (DWB-307 TL helper)
# Caller: pytest
# Callees: app.routers.agents, app.services.hook_tracking.resolve_agent_from_marker
# Data In: pytest fixtures (make_project, make_agent), tmp_path
# Data Out: assertions
# Last Modified: 2026-06-05

"""DWB-307 — POST /api/agents/{id}/marker writes the JSON marker file
that the hook resolver reads.

Each test creates a project with a real `repo_path` (tmp_path) so the
endpoint actually lands a file on disk. Round-trip tests then prove the
resolver picks the same marker up — closing the doc/impl gap that DWB-307
exists to fix.
"""

import json

from app.models.project import Project
from app.services import hook_tracking


def test_marker_endpoint_writes_json_file_with_required_fields(
    client, make_project, make_agent, tmp_path
):
    """The endpoint writes a JSON dict with agent_id + identifying fields."""
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"], role="backend-worker", name="Devin")

    r = client.post(
        f"/api/agents/{agent['id']}/marker",
        json={"session_id": "abc-123"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["agent_id"] == agent["id"]
    assert body["session_id"] == "abc-123"

    expected_path = tmp_path / ".claude" / "agents" / "active" / "abc-123"
    assert expected_path.is_file()
    payload = json.loads(expected_path.read_text())
    assert payload["agent_id"] == agent["id"]
    assert payload["agent_name"] == "Devin"
    assert payload["role"] == "backend-worker"
    assert payload["project_prefix"] == project["prefix"]


def test_marker_endpoint_overwrites_existing_marker(
    client, make_project, make_agent, tmp_path
):
    """Re-issuing for the same session_id overwrites — idempotent for TL retries."""
    project = make_project(repo_path=str(tmp_path))
    agent_a = make_agent(project_id=project["id"], role="backend-worker", name="Devin")
    agent_b = make_agent(project_id=project["id"], role="backend-worker", name="Barry")

    client.post(f"/api/agents/{agent_a['id']}/marker", json={"session_id": "s-1"})
    r = client.post(
        f"/api/agents/{agent_b['id']}/marker", json={"session_id": "s-1"}
    )
    assert r.status_code == 201

    marker = tmp_path / ".claude" / "agents" / "active" / "s-1"
    payload = json.loads(marker.read_text())
    assert payload["agent_id"] == agent_b["id"]
    assert payload["agent_name"] == "Barry"


def test_marker_endpoint_404_for_missing_agent(client, make_project, tmp_path):
    make_project(repo_path=str(tmp_path))
    r = client.post("/api/agents/99999/marker", json={"session_id": "x"})
    assert r.status_code == 404


def test_marker_endpoint_400_for_empty_session_id(
    client, make_project, make_agent, tmp_path
):
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"])
    r = client.post(f"/api/agents/{agent['id']}/marker", json={"session_id": "   "})
    assert r.status_code == 400


def test_marker_endpoint_400_when_project_has_no_repo_path(
    client, make_project, make_agent
):
    """No repo_path means no place to land the marker — must surface, not 500."""
    project = make_project()  # no repo_path
    agent = make_agent(project_id=project["id"])
    r = client.post(
        f"/api/agents/{agent['id']}/marker", json={"session_id": "y"}
    )
    assert r.status_code == 400


def test_marker_endpoint_round_trip_resolves_to_named_agent(
    client, db_session, make_project, make_agent, tmp_path
):
    """End-to-end: TL writes marker → hook resolver picks the same agent.

    This is the regression test for the original DWB-307 bug — single-line
    int markers used to be rejected by the resolver, leaving the TL with
    no working path to attribute a session.
    """
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"], role="team-lead", name="Archie")

    r = client.post(
        f"/api/agents/{agent['id']}/marker", json={"session_id": "round-trip-1"}
    )
    assert r.status_code == 201

    project_row = db_session.get(Project, project["id"])
    resolved = hook_tracking.resolve_agent_from_marker(
        db_session,
        project_row,
        session_id="round-trip-1",
        hook_event="SessionEnd",
        hook_data={},
    )
    assert resolved is not None
    assert resolved.id == agent["id"]
    assert resolved.name == "Archie"
    assert resolved.role == "team-lead"
