# Path:          tests/test_hooks.py
# File:          test_hooks.py
# Created:       2026-04-09
# Purpose:       Tests for hook-based passive tracking — session lifecycle, transcript parsing,
#                agent resolution, work context, and end-to-end rollup
# Caller:        pytest
# Callees:       POST /api/hooks/session-start|session-end,
#                GET /api/hooks/sessions, GET /api/tracking/summary,
#                app.services.hook_tracking (parse_transcript, resolve_agent)
# Data In:       Factory-created projects, agents, tickets via conftest fixtures; JSONL transcripts
# Data Out:      Assertions on hook_session records, tracking events, summary aggregations
# Last Modified: 2026-04-09

"""Tests for passive hook-based tracking (Phase 8)."""

import json
import time
import uuid

import pytest

from app.services.hook_tracking import parse_transcript, resolve_agent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def make_transcript(tmp_path):
    """Factory that writes JSONL transcript files with configurable content.

    Args:
        agent_name: Name written to agentName field (first line)
        messages: List of dicts with token usage, e.g.
            [{"input_tokens": 100, "output_tokens": 50}]
        timestamps: List of ISO timestamp strings (one per message)
    """
    _counter = [0]

    def _make(agent_name="backend-worker", messages=None, timestamps=None):
        _counter[0] += 1
        path = tmp_path / f"transcript_{_counter[0]}.jsonl"

        lines = []
        # First line: agent identity
        if agent_name:
            lines.append(json.dumps({"agentName": agent_name}))

        if messages is None:
            messages = [{"input_tokens": 100, "output_tokens": 50}]

        for i, usage in enumerate(messages):
            entry = {
                "usage": {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                },
            }
            if timestamps and i < len(timestamps):
                entry["timestamp"] = timestamps[i]
            lines.append(json.dumps(entry))

        path.write_text("\n".join(lines) + "\n")
        return str(path)

    return _make


@pytest.fixture
def hook_project(client, make_project):
    """Create a project with repo_path set for cwd matching."""
    return make_project(repo_path="/tmp/test-project")


@pytest.fixture
def hook_agent_worker(client, make_agent):
    """Create a worker agent (backend-worker role)."""
    return make_agent(name="Bravo", role="backend-worker")


@pytest.fixture
def hook_agent_tl(client, make_agent):
    """Create a team-lead agent (overhead role)."""
    return make_agent(name="Archie", role="team-lead")


@pytest.fixture
def hook_agent_pm(client, make_agent):
    """Create a PM agent (overhead role)."""
    return make_agent(name="Percy", role="pm")


def _assign_agent(client, project_id, agent_id):
    """Helper to assign an agent to a project."""
    r = client.post("/api/project-agents", json={
        "project_id": project_id, "agent_id": agent_id,
    })
    assert r.status_code == 201
    return r.json()


def _session_id():
    """Generate a unique session ID."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# TestSessionStart
# ---------------------------------------------------------------------------

class TestSessionStart:
    """POST /api/hooks/session-start lifecycle."""

    def test_returns_200_with_ok(self, client, hook_project, hook_agent_worker):
        _assign_agent(client, hook_project["id"], hook_agent_worker["id"])
        r = client.post("/api/hooks/session-start", json={
            "session_id": _session_id(),
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "session_id" in data
        assert "hook_session_id" in data

    def test_creates_hook_session(self, client, hook_project, hook_agent_worker):
        _assign_agent(client, hook_project["id"], hook_agent_worker["id"])
        sid = _session_id()
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        # Verify via GET
        r = client.get(f"/api/hooks/sessions/{sid}")
        assert r.status_code == 200
        session = r.json()
        assert session["session_id"] == sid
        assert session["status"] == "active"
        assert session["agent_name"] == "backend-worker"

    def test_idempotent_same_session_id(self, client, hook_project, hook_agent_worker):
        _assign_agent(client, hook_project["id"], hook_agent_worker["id"])
        sid = _session_id()
        payload = {
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        }
        r1 = client.post("/api/hooks/session-start", json=payload)
        r2 = client.post("/api/hooks/session-start", json=payload)
        assert r1.json()["hook_session_id"] == r2.json()["hook_session_id"]

    def test_creates_tracking_start_for_worker(
        self, client, hook_project, hook_agent_worker, make_epic, make_sprint, make_ticket
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=hook_agent_worker["id"], status="in_progress",
        )
        client.post("/api/hooks/session-start", json={
            "session_id": _session_id(),
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        # Summary should show the ticket with tracking data
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        ticket_entry = [t for t in data["per_ticket"] if t["ticket_id"] == ticket["id"]]
        assert len(ticket_entry) >= 1

    def test_creates_overhead_start_for_tl(self, client, hook_project, hook_agent_tl):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_tl["id"])
        client.post("/api/hooks/session-start", json={
            "session_id": _session_id(),
            "cwd": "/tmp/test-project",
            "agent_name": "team-lead",
        })
        data = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        # Overhead should have started (can't verify exact seconds without stop,
        # but per_agent should show the agent)
        assert len(data["per_agent"]) >= 1

    def test_error_no_project_match(self, client):
        r = client.post("/api/hooks/session-start", json={
            "session_id": _session_id(),
            "cwd": "/nonexistent/path",
        })
        assert r.status_code == 200  # Never 5xx
        assert r.json()["status"] == "error"


# ---------------------------------------------------------------------------
# TestSessionEnd
# ---------------------------------------------------------------------------

class TestSessionEnd:
    """POST /api/hooks/session-end lifecycle."""

    def test_returns_200_with_ok_and_tokens(
        self, client, hook_project, hook_agent_worker, make_transcript,
        make_epic, make_sprint, make_ticket,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=hook_agent_worker["id"], status="in_progress",
        )
        sid = _session_id()
        transcript = make_transcript(
            agent_name="backend-worker",
            messages=[{"input_tokens": 500, "output_tokens": 200}],
        )
        # Start then end
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["total_tokens"] == 700

    def test_session_marked_completed(
        self, client, hook_project, hook_agent_worker, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        sid = _session_id()
        transcript = make_transcript(agent_name="backend-worker")
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["status"] == "completed"
        assert session["end_time"] is not None

    def test_token_breakdown_stored(
        self, client, hook_project, hook_agent_worker, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        sid = _session_id()
        transcript = make_transcript(
            agent_name="backend-worker",
            messages=[{
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": 50,
            }],
        )
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
        })
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        bd = session["token_breakdown"]
        assert bd["input"] == 100
        assert bd["output"] == 200
        assert bd["cache_creation"] == 30
        assert bd["cache_read"] == 50
        assert session["total_tokens"] == 380

    def test_creates_stop_and_token_report_for_worker(
        self, client, hook_project, hook_agent_worker, make_transcript,
        make_epic, make_sprint, make_ticket,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=hook_agent_worker["id"], status="in_progress",
        )
        sid = _session_id()
        transcript = make_transcript(
            agent_name="backend-worker",
            messages=[{"input_tokens": 1000, "output_tokens": 500}],
        )
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        time.sleep(1.1)
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        summary = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        ticket_entry = [t for t in summary["per_ticket"] if t["ticket_id"] == ticket["id"]]
        assert len(ticket_entry) == 1
        assert ticket_entry[0]["tokens"] == 1500
        assert ticket_entry[0]["time_seconds"] >= 1

    def test_overhead_stop_for_tl(
        self, client, hook_project, hook_agent_tl, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_tl["id"])
        sid = _session_id()
        transcript = make_transcript(agent_name="team-lead")
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "team-lead",
        })
        time.sleep(1.1)
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        summary = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert summary["project_total"]["overhead_time_seconds"] >= 1

    def test_retroactive_session_without_prior_start(
        self, client, hook_project, hook_agent_worker, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        sid = _session_id()
        transcript = make_transcript(
            agent_name="backend-worker",
            messages=[{"input_tokens": 300, "output_tokens": 100}],
        )
        # session-end without a prior session-start
        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "transcript_path": transcript,
            "agent_name": "backend-worker",
            "hook_event": "SubagentStop",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["total_tokens"] == 400
        # Session should be created and completed
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["status"] == "completed"

    def test_idempotent_completed_session(
        self, client, hook_project, hook_agent_worker, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        sid = _session_id()
        transcript = make_transcript(agent_name="backend-worker")
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        r1 = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
        })
        r2 = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
        })
        assert r1.json()["hook_session_id"] == r2.json()["hook_session_id"]


# ---------------------------------------------------------------------------
# TestTranscriptParser
# ---------------------------------------------------------------------------

class TestTranscriptParser:
    """Direct tests for parse_transcript service function."""

    def test_counts_all_four_token_types(self, make_transcript):
        path = make_transcript(
            agent_name="test",
            messages=[{
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 75,
            }],
        )
        result = parse_transcript(path)
        assert result["total_tokens"] == 425
        assert result["breakdown"]["input"] == 100
        assert result["breakdown"]["output"] == 200
        assert result["breakdown"]["cache_creation"] == 50
        assert result["breakdown"]["cache_read"] == 75

    def test_sums_multiple_messages(self, make_transcript):
        path = make_transcript(
            agent_name="test",
            messages=[
                {"input_tokens": 100, "output_tokens": 50},
                {"input_tokens": 200, "output_tokens": 100},
                {"input_tokens": 300, "output_tokens": 150},
            ],
        )
        result = parse_transcript(path)
        assert result["total_tokens"] == 900
        assert result["breakdown"]["input"] == 600
        assert result["breakdown"]["output"] == 300

    def test_extracts_end_time_from_last_timestamp(self, make_transcript):
        path = make_transcript(
            agent_name="test",
            messages=[
                {"input_tokens": 10, "output_tokens": 5},
                {"input_tokens": 20, "output_tokens": 10},
            ],
            timestamps=[
                "2026-04-09T10:00:00Z",
                "2026-04-09T10:05:00Z",
            ],
        )
        result = parse_transcript(path)
        assert result["end_time"] is not None
        assert result["end_time"].minute == 5

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        result = parse_transcript(str(path))
        assert result["total_tokens"] == 0
        assert result["breakdown"]["input"] == 0
        assert result["end_time"] is None

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "malformed.jsonl"
        lines = [
            "this is not json",
            json.dumps({"usage": {"input_tokens": 100, "output_tokens": 50}}),
            "{bad json{",
            json.dumps({"usage": {"input_tokens": 200, "output_tokens": 100}}),
        ]
        path.write_text("\n".join(lines) + "\n")
        result = parse_transcript(str(path))
        assert result["total_tokens"] == 450
        assert result["breakdown"]["input"] == 300
        assert result["breakdown"]["output"] == 150

    def test_missing_file(self, tmp_path):
        result = parse_transcript(str(tmp_path / "nonexistent.jsonl"))
        assert result["total_tokens"] == 0
        assert result["end_time"] is None


# ---------------------------------------------------------------------------
# TestAgentResolution
# ---------------------------------------------------------------------------

class TestAgentResolution:
    """Direct tests for resolve_agent service function."""

    def test_matches_by_role(self, db_session, client, hook_project, hook_agent_worker):
        _assign_agent(client, hook_project["id"], hook_agent_worker["id"])
        agent = resolve_agent(db_session, "backend-worker", hook_project["id"])
        assert agent is not None
        assert agent.id == hook_agent_worker["id"]
        assert agent.role == "backend-worker"

    def test_matches_by_name_fallback(self, db_session, client, hook_project, hook_agent_worker):
        _assign_agent(client, hook_project["id"], hook_agent_worker["id"])
        # Match by name "Bravo" (case-insensitive)
        agent = resolve_agent(db_session, "bravo", hook_project["id"])
        assert agent is not None
        assert agent.id == hook_agent_worker["id"]

    def test_returns_none_for_unknown(self, db_session, client, hook_project, hook_agent_worker):
        _assign_agent(client, hook_project["id"], hook_agent_worker["id"])
        agent = resolve_agent(db_session, "unknown-agent", hook_project["id"])
        assert agent is None

    def test_scoped_to_project(self, db_session, client, make_project, hook_agent_worker):
        # Agent is NOT assigned to this project
        other_project = make_project(repo_path="/tmp/other-project")
        agent = resolve_agent(db_session, "backend-worker", other_project["id"])
        assert agent is None

    def test_returns_none_for_none_name(self, db_session, hook_project):
        agent = resolve_agent(db_session, None, hook_project["id"])
        assert agent is None


# ---------------------------------------------------------------------------
# TestWorkContext
# ---------------------------------------------------------------------------

class TestWorkContext:
    """Work context attribution — overhead vs ticket work via hook endpoints."""

    def test_tl_creates_overhead(self, client, hook_project, hook_agent_tl):
        _assign_agent(client, hook_project["id"], hook_agent_tl["id"])
        sid = _session_id()
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "team-lead",
        })
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["session_type"] == "main"
        assert session["ticket_id"] is None

    def test_pm_creates_overhead(self, client, hook_project, hook_agent_pm):
        _assign_agent(client, hook_project["id"], hook_agent_pm["id"])
        sid = _session_id()
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "pm",
        })
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["session_type"] == "main"
        assert session["ticket_id"] is None

    def test_worker_finds_in_progress_ticket(
        self, client, hook_project, hook_agent_worker,
        make_epic, make_sprint, make_ticket,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=hook_agent_worker["id"], status="in_progress",
        )
        sid = _session_id()
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["session_type"] == "teammate"
        assert session["ticket_id"] == ticket["id"]

    def test_worker_falls_back_to_todo_ticket(
        self, client, hook_project, hook_agent_worker,
        make_epic, make_sprint, make_ticket,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=hook_agent_worker["id"], status="todo",
        )
        sid = _session_id()
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["ticket_id"] == ticket["id"]

    def test_worker_no_ticket_returns_none(
        self, client, hook_project, hook_agent_worker,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        sid = _session_id()
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["ticket_id"] is None


# ---------------------------------------------------------------------------
# TestEndToEndRollup
# ---------------------------------------------------------------------------

class TestEndToEndRollup:
    """Full flow: session-start → session-end → tracking/summary shows data."""

    def test_full_flow_tokens_in_summary(
        self, client, hook_project, hook_agent_worker, make_transcript,
        make_epic, make_sprint, make_ticket,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=hook_agent_worker["id"], status="in_progress",
        )
        sid = _session_id()
        transcript = make_transcript(
            agent_name="backend-worker",
            messages=[
                {"input_tokens": 500, "output_tokens": 300, "cache_read_input_tokens": 200},
                {"input_tokens": 400, "output_tokens": 200, "cache_creation_input_tokens": 100},
            ],
        )
        # Start
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "backend-worker",
        })
        time.sleep(1.1)
        # End
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        # Verify summary
        summary = client.get("/api/tracking/summary", params={"project_id": pid}).json()

        # Per-ticket: tokens = 500+300+200+400+200+100 = 1700
        ticket_entry = [t for t in summary["per_ticket"] if t["ticket_id"] == ticket["id"]]
        assert len(ticket_entry) == 1
        assert ticket_entry[0]["tokens"] == 1700
        assert ticket_entry[0]["time_seconds"] >= 1

        # Per-agent
        agent_entry = [a for a in summary["per_agent"] if a["agent_id"] == hook_agent_worker["id"]]
        assert len(agent_entry) == 1
        assert agent_entry[0]["tokens"] == 1700

        # Project total
        assert summary["project_total"]["tokens"] == 1700
        assert summary["project_total"]["time_seconds"] >= 1

    def test_overhead_flow_in_summary(
        self, client, hook_project, hook_agent_tl, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_tl["id"])
        sid = _session_id()
        transcript = make_transcript(
            agent_name="team-lead",
            messages=[{"input_tokens": 800, "output_tokens": 400}],
        )
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
            "agent_name": "team-lead",
        })
        time.sleep(1.1)
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })
        summary = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert summary["project_total"]["overhead_time_seconds"] >= 1
        assert summary["project_total"]["overhead_tokens"] == 1200
        # Overhead tokens are not in per_ticket
        assert summary["per_ticket"] == []


class TestTLFallback:
    """When a main CLI session has no agent name, attribute to TL as overhead."""

    def test_main_session_attributed_to_tl(
        self, client, hook_project, hook_agent_tl, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_tl["id"])
        sid = _session_id()

        # No agent_name — simulates user running Claude Code directly
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
        })

        r = client.get(f"/api/hooks/sessions/{sid}")
        session = r.json()
        assert session["agent_id"] == hook_agent_tl["id"]
        assert session["session_type"] == "main"

    def test_main_session_tokens_go_to_overhead(
        self, client, hook_project, hook_agent_tl, make_transcript,
    ):
        pid = hook_project["id"]
        _assign_agent(client, pid, hook_agent_tl["id"])
        sid = _session_id()

        # No agent_name in transcript either
        transcript = make_transcript(
            agent_name=None,
            messages=[{"input_tokens": 500, "output_tokens": 300}],
        )

        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
        })
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })

        summary = client.get("/api/tracking/summary", params={"project_id": pid}).json()
        assert summary["project_total"]["overhead_tokens"] == 800
        assert summary["per_ticket"] == []

    def test_no_tl_agent_fires_unattributed_alert(
        self, client, hook_project, make_transcript, make_agent,
    ):
        """If no TL is assigned to the project, tokens are unattributed → alert."""
        pid = hook_project["id"]
        # Assign a worker (not TL) so project has agents but no TL
        worker = make_agent(name="Worker", role="frontend-worker")
        _assign_agent(client, pid, worker["id"])
        sid = _session_id()

        transcript = make_transcript(
            agent_name=None,
            messages=[{"input_tokens": 200, "output_tokens": 100}],
        )

        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": "/tmp/test-project",
        })
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "transcript_path": transcript,
            "hook_event": "SessionEnd",
        })

        # Should have an unattributed alert
        alerts = client.get("/api/alerts").json()
        unattributed = [a for a in alerts if "Unattributed" in a.get("title", "")]
        assert len(unattributed) >= 1
