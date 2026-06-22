# Path: tests/test_hook_tool_use.py
# File: test_hook_tool_use.py
# Created: 2026-06-22
# Purpose: DWB-417..421 acceptance - POST /api/hooks/tool-use + /lifecycle-event
#          persist tool_actions rows, resolve agent/ticket/dwb_session context
#          from session_id, classify per tool (file_written / message_sent /
#          agent_spawned / notification / context_compaction), emit semantic
#          activity-feed verbs, and degrade gracefully (200 + null context).
# Caller: pytest
# Callees: POST /api/hooks/tool-use, POST /api/hooks/lifecycle-event,
#          POST /api/hooks/session-start, GET /api/projects/{id}/activity-feed,
#          app.models.tool_action.ToolAction
# Data In: Factory-created projects/agents/tickets; tmp_path marker files
# Data Out: Assertions on ToolAction rows, endpoint responses, activity feed
# Last Modified: 2026-06-22 (DWB-418..421)

"""Tests for the PostToolUse tool-action capture endpoint (DWB-417)."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.models.tool_action import ToolAction


def _assign(client, project_id, agent_id):
    r = client.post("/api/project-agents", json={
        "project_id": project_id, "agent_id": agent_id,
    })
    assert r.status_code == 201


def _session_id():
    return str(uuid.uuid4())


@pytest.fixture
def tool_project(client, make_project, tmp_path):
    """Project rooted at tmp_path so marker files can be written into it."""
    return make_project(repo_path=str(tmp_path))


def _write_marker(repo_path, session_id, *, agent_id):
    marker_dir = repo_path / ".claude" / "agents" / "active"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / session_id).write_text(
        json.dumps({"agent_id": agent_id}), encoding="utf-8"
    )


class TestToolUseEndpoint:
    """POST /api/hooks/tool-use foundation behavior."""

    def test_returns_200_and_persists_row(self, client, tool_project, db_session):
        sid = _session_id()
        # A generic (unclassified) tool persists a bare row with the generic
        # event and no target/metadata.
        r = client.post("/api/hooks/tool-use", json={
            "session_id": sid,
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x.py"},
            "cwd": str(tool_project["repo_path"]),
            "hook_event_name": "PostToolUse",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "tool_action_id" in data

        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row is not None
        assert row.session_id == sid
        assert row.tool_name == "Read"
        # Generic event, no per-tool classification.
        assert row.event_type == "tool_use"
        assert row.target is None
        assert row.tool_metadata is None

    def test_resolves_agent_and_ticket_from_existing_session(
        self, client, tool_project, make_agent,
        make_epic, make_sprint, make_ticket, db_session,
    ):
        pid = tool_project["id"]
        worker = make_agent(
            project_id=pid, name="ToolWorker", role="backend-worker",
            api_key="tool-use-worker",
        )
        _assign(client, pid, worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=worker["id"], status="in_progress",
        )

        sid = _session_id()
        # session-start creates a hook_session keyed on session_id with the
        # resolved agent + ticket context.
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": str(tool_project["repo_path"]),
            "agent_name": "backend-worker",
        })

        r = client.post("/api/hooks/tool-use", json={
            "session_id": sid,
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/y.py"},
            "cwd": str(tool_project["repo_path"]),
        })
        assert r.status_code == 200
        data = r.json()
        assert data["agent_id"] == worker["id"]
        assert data["ticket_id"] == ticket["id"]

        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row.agent_id == worker["id"]
        assert row.ticket_id == ticket["id"]

    def test_resolves_agent_from_marker_without_prior_session(
        self, client, tool_project, tmp_path, make_agent,
        make_epic, make_sprint, make_ticket, db_session,
    ):
        pid = tool_project["id"]
        worker = make_agent(
            project_id=pid, name="MarkerWorker", role="backend-worker",
            api_key="tool-use-marker-worker",
        )
        _assign(client, pid, worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=worker["id"], status="in_progress",
        )

        sid = _session_id()
        # No prior session-start; an authoritative marker points at the worker.
        _write_marker(tmp_path, sid, agent_id=worker["id"])

        r = client.post("/api/hooks/tool-use", json={
            "session_id": sid,
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "cwd": str(tool_project["repo_path"]),
        })
        assert r.status_code == 200
        data = r.json()
        assert data["agent_id"] == worker["id"]
        assert data["ticket_id"] == ticket["id"]

    def test_unknown_session_degrades_to_null_context(
        self, client, tool_project, db_session,
    ):
        # Unknown session_id, no marker, no hook_session: must still 200 and
        # persist a row with null agent/ticket (delivery-gap tolerance).
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/z.py"},
            "cwd": str(tool_project["repo_path"]),
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row is not None
        assert row.agent_id is None
        assert row.ticket_id is None

    def test_missing_session_id_still_200(self, client, tool_project, db_session):
        # No session_id and an unknown cwd: never 4xx/5xx; persist a bare row.
        r = client.post("/api/hooks/tool-use", json={
            "tool_name": "Glob",
            "tool_input": {"pattern": "*.py"},
            "cwd": "/nonexistent/path",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row is not None
        assert row.session_id is None
        assert row.agent_id is None
        assert row.tool_name == "Glob"

    def test_empty_payload_still_200(self, client):
        # Fully empty payload (worst case): never raises out to the caller.
        r = client.post("/api/hooks/tool-use", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def _feed(client, project_id, action=None):
    rows = client.get(
        f"/api/projects/{project_id}/activity-feed", params={"limit": 500}
    ).json()
    if action is not None:
        rows = [r for r in rows if r["action"] == action]
    return rows


class TestFileWriteClassification:
    """DWB-418: Write/Edit/MultiEdit/NotebookEdit -> file_written + target."""

    @pytest.mark.parametrize("tool_name", ["Write", "Edit", "MultiEdit"])
    def test_file_path_tools_classify_file_written(
        self, client, tool_project, db_session, tool_name,
    ):
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": tool_name,
            "tool_input": {"file_path": "/repo/app/x.py"},
            "cwd": str(tool_project["repo_path"]),
        })
        assert r.status_code == 200
        data = r.json()
        assert data["event_type"] == "file_written"
        assert data["target"] == "/repo/app/x.py"
        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row.event_type == "file_written"
        assert row.target == "/repo/app/x.py"

    def test_notebook_edit_uses_notebook_path(
        self, client, tool_project, db_session,
    ):
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": "/repo/nb.ipynb"},
            "cwd": str(tool_project["repo_path"]),
        })
        data = r.json()
        assert data["event_type"] == "file_written"
        assert data["target"] == "/repo/nb.ipynb"

    def test_file_written_emits_feed_verb(self, client, tool_project):
        sid = _session_id()
        r = client.post("/api/hooks/tool-use", json={
            "session_id": sid,
            "tool_name": "Write",
            "tool_input": {"file_path": "/repo/feed.py"},
            "cwd": str(tool_project["repo_path"]),
        })
        action_id = r.json()["tool_action_id"]
        rows = _feed(client, tool_project["id"], action="file_written")
        match = [r for r in rows if r["entity_id"] == action_id]
        assert len(match) == 1
        assert match[0]["entity_type"] == "tool_action"
        assert match[0]["details"]["target"] == "/repo/feed.py"


class TestSendMessageClassification:
    """DWB-419: SendMessage -> message_sent, target=recipient, no body."""

    def test_message_sent_classification_no_body(
        self, client, tool_project, db_session,
    ):
        secret_body = "DO NOT PERSIST THIS BODY TEXT"
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": "SendMessage",
            "tool_input": {
                "to": "Archie_DWB",
                "summary": "status update",
                "message": secret_body,
            },
            "cwd": str(tool_project["repo_path"]),
        })
        data = r.json()
        assert data["event_type"] == "message_sent"
        assert data["target"] == "Archie_DWB"

        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row.target == "Archie_DWB"
        assert row.tool_metadata == {"subject": "status update"}
        # The message BODY must never be persisted anywhere on the row.
        serialized = f"{row.target}{row.tool_metadata}"
        assert secret_body not in serialized

    def test_message_sent_emits_feed_verb_without_body(self, client, tool_project):
        secret_body = "private contents here"
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": "SendMessage",
            "tool_input": {"to": "Pam_DWB", "summary": "ping", "message": secret_body},
            "cwd": str(tool_project["repo_path"]),
        })
        action_id = r.json()["tool_action_id"]
        rows = _feed(client, tool_project["id"], action="message_sent")
        match = [r for r in rows if r["entity_id"] == action_id]
        assert len(match) == 1
        assert match[0]["details"]["target"] == "Pam_DWB"
        assert secret_body not in str(match[0]["details"])


class TestTaskClassification:
    """DWB-420: Task -> agent_spawned, target=child identity."""

    def test_task_uses_subagent_type_as_target(
        self, client, tool_project, db_session,
    ):
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "backend-worker",
                "description": "build the thing",
                "prompt": "long prompt body",
            },
            "cwd": str(tool_project["repo_path"]),
        })
        data = r.json()
        assert data["event_type"] == "agent_spawned"
        assert data["target"] == "backend-worker"
        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row.tool_metadata == {"description": "build the thing"}

    def test_task_falls_back_to_description_when_no_type(
        self, client, tool_project,
    ):
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": "Task",
            "tool_input": {"description": "investigate flaky test"},
            "cwd": str(tool_project["repo_path"]),
        })
        data = r.json()
        assert data["event_type"] == "agent_spawned"
        assert data["target"] == "investigate flaky test"

    def test_task_emits_feed_verb(self, client, tool_project):
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": "Task",
            "tool_input": {"subagent_type": "tester", "description": "run suite"},
            "cwd": str(tool_project["repo_path"]),
        })
        action_id = r.json()["tool_action_id"]
        rows = _feed(client, tool_project["id"], action="agent_spawned")
        assert any(r["entity_id"] == action_id for r in rows)


class TestGenericFallback:
    """Unmatched tools keep the generic 'tool_use' event and emit NO feed verb."""

    @pytest.mark.parametrize("tool_name", ["Read", "Bash", "Grep", "Glob"])
    def test_unmatched_tool_is_generic_no_feed(
        self, client, tool_project, tool_name,
    ):
        r = client.post("/api/hooks/tool-use", json={
            "session_id": _session_id(),
            "tool_name": tool_name,
            "tool_input": {"file_path": "/repo/x.py"},
            "cwd": str(tool_project["repo_path"]),
        })
        data = r.json()
        assert data["event_type"] == "tool_use"
        assert data["target"] is None
        # No semantic feed verb for generic tool use (feed-noise control).
        feed = _feed(client, tool_project["id"])
        action_ids = {r["entity_id"] for r in feed if r["entity_type"] == "tool_action"}
        assert data["tool_action_id"] not in action_ids


class TestLifecycleEvents:
    """DWB-421: Notification + PreCompact via /api/hooks/lifecycle-event."""

    def test_notification_classification_and_feed(
        self, client, tool_project, db_session,
    ):
        r = client.post("/api/hooks/lifecycle-event", json={
            "session_id": _session_id(),
            "hook_event_name": "Notification",
            "message": "Claude needs your permission to use Bash",
            "cwd": str(tool_project["repo_path"]),
        })
        assert r.status_code == 200
        data = r.json()
        assert data["event_type"] == "notification"
        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row.tool_name == "Notification"
        assert row.target == "Claude needs your permission to use Bash"
        rows = _feed(client, tool_project["id"], action="notification")
        assert any(r["entity_id"] == data["tool_action_id"] for r in rows)

    def test_precompact_classification_and_feed(
        self, client, tool_project, db_session,
    ):
        r = client.post("/api/hooks/lifecycle-event", json={
            "session_id": _session_id(),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
            "cwd": str(tool_project["repo_path"]),
        })
        data = r.json()
        assert data["event_type"] == "context_compaction"
        row = db_session.scalar(
            select(ToolAction).where(ToolAction.id == data["tool_action_id"])
        )
        assert row.tool_name == "PreCompact"
        assert row.target == "auto"
        rows = _feed(client, tool_project["id"], action="context_compaction")
        assert any(r["entity_id"] == data["tool_action_id"] for r in rows)

    def test_unknown_lifecycle_event_is_generic_no_feed(
        self, client, tool_project,
    ):
        r = client.post("/api/hooks/lifecycle-event", json={
            "session_id": _session_id(),
            "hook_event_name": "Mystery",
            "cwd": str(tool_project["repo_path"]),
        })
        data = r.json()
        assert data["status"] == "ok"
        assert data["event_type"] == "tool_use"
        feed = _feed(client, tool_project["id"])
        action_ids = {r["entity_id"] for r in feed if r["entity_type"] == "tool_action"}
        assert data["tool_action_id"] not in action_ids

    def test_lifecycle_empty_payload_still_200(self, client):
        r = client.post("/api/hooks/lifecycle-event", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
