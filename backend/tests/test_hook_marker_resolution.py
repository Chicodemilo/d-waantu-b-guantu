# Path: tests/test_hook_marker_resolution.py
# File: test_hook_marker_resolution.py
# Created: 2026-06-04
# Purpose: DWB-294 acceptance gate — marker-based attribution on SubagentStop and
#          SessionEnd paths. Asserts tokens land where the marker says, not where
#          legacy agent_name resolve would have routed them.
# Caller: pytest
# Callees: POST /api/hooks/session-start|session-end, GET /api/tracking/summary
# Data In: tmp_path-rooted .claude/agents/active/<sid> marker files; JSONL transcripts
# Data Out: Assertions on hook_session.agent_id, tracking_log via summary, ticket.tokens_used
# Last Modified: 2026-06-04

"""DWB-294 marker-resolution acceptance gate.

Existing test_hook_session_marker.py covers SessionStart. This file covers
the two remaining paths and the end-to-end token-landing check:

  1. SubagentStop with marker  — _handle_subagent_stop (hook_tracking.py:587)
  2. SessionEnd with marker    — both the "no prior start" branch (line 187)
                                  and the "re-resolve on end" branch (line 240)
  3. End-to-end tokens         — assert tracking_log + ticket.tokens_used,
                                  not just hook_session.agent_id

These tests prove the marker is authoritative even when the hook payload
carries a misleading agent_type / agent_name. Without these, DWB-294 has
no enforcement for the paths that actually deliver Pam's tokens.
"""

import json
import os
import time
import uuid

import pytest


def _write_marker(repo_path, session_id, *, agent_id: int):
    marker_dir = repo_path / ".claude" / "agents" / "active"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / session_id).write_text(
        json.dumps({"agent_id": agent_id}), encoding="utf-8"
    )


def _write_transcript(tmp_path, *, name: str, input_tokens: int, output_tokens: int) -> str:
    """Minimal JSONL transcript that parse_transcript() can consume."""
    path = tmp_path / f"transcript_{name}_{uuid.uuid4().hex[:8]}.jsonl"
    lines = [
        json.dumps({"agentName": name}),
        json.dumps({"usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }}),
    ]
    path.write_text("\n".join(lines) + "\n")
    return str(path)


@pytest.fixture
def marker_project(client, make_project, tmp_path):
    """Project rooted at tmp_path so we can write marker files into it."""
    return make_project(repo_path=str(tmp_path))


def _assign(client, project_id, agent_id):
    r = client.post("/api/project-agents", json={
        "project_id": project_id, "agent_id": agent_id,
    })
    assert r.status_code == 201


class TestSubagentStopMarker:
    """SubagentStop is the path Teams subagents take. Marker-driven attribution
    here is what DWB-294 was built for."""

    def test_marker_attributes_to_named_agent_on_subagent_stop(
        self, client, marker_project, tmp_path, make_agent,
    ):
        # Agent the marker points at (correct target).
        correct = make_agent(
            project_id=marker_project["id"], name="Pixel",
            role="frontend-worker", api_key="sub-stop-marker-pixel",
        )
        _assign(client, marker_project["id"], correct["id"])
        # Decoy agent matching the agent_type the hook payload will carry.
        # If the marker is ignored, the legacy resolve picks this one.
        decoy = make_agent(
            project_id=marker_project["id"], name="Decoy-FE",
            role="frontend-worker-2", api_key="sub-stop-marker-decoy",
        )
        _assign(client, marker_project["id"], decoy["id"])

        subagent_session_id = f"sub-{uuid.uuid4()}"
        _write_marker(tmp_path, subagent_session_id, agent_id=correct["id"])

        r = client.post("/api/hooks/session-end", json={
            "session_id": "irrelevant-parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_session_id,
            "agent_type": "frontend-worker-2",  # would match decoy
            "agent_transcript_path": _write_transcript(
                tmp_path, name="pixel", input_tokens=100, output_tokens=50,
            ),
        })
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Look up the SubagentStop session row — keyed on subagent_session_id,
        # NOT the parent session_id.
        session = client.get(f"/api/hooks/sessions/{subagent_session_id}").json()
        assert session["agent_id"] == correct["id"], (
            f"marker pointed at agent {correct['id']} but session attributed to "
            f"{session['agent_id']} — marker resolution failed on SubagentStop path"
        )

    def test_subagent_stop_marker_tokens_land_on_assigned_ticket(
        self, client, marker_project, tmp_path, make_agent, make_epic, make_sprint, make_ticket,
    ):
        """End-to-end: marker → tracking_log row → ticket.tokens_used incremented."""
        pid = marker_project["id"]
        worker = make_agent(
            project_id=pid, name="Devin",
            role="backend-worker", api_key="sub-stop-tokens-devin",
        )
        _assign(client, pid, worker["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=worker["id"], status="in_progress",
        )

        subagent_session_id = f"sub-tok-{uuid.uuid4()}"
        _write_marker(tmp_path, subagent_session_id, agent_id=worker["id"])

        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_session_id,
            "agent_type": "backend-worker",
            "agent_transcript_path": _write_transcript(
                tmp_path, name="devin", input_tokens=800, output_tokens=400,
            ),
        })

        # 1. Ticket.tokens_used incremented + source tagged "hook"
        t = client.get(f"/api/tickets/{ticket['id']}").json()
        assert t["tokens_used"] == 1200
        assert t["token_source"] == "hook"

        # 2. Tracking summary attributes tokens to this worker + this ticket
        summary = client.get(
            "/api/tracking/summary", params={"project_id": pid}
        ).json()
        per_ticket = [r for r in summary["per_ticket"] if r["ticket_id"] == ticket["id"]]
        assert per_ticket, "ticket missing from /api/tracking/summary per_ticket"
        assert per_ticket[0]["tokens"] == 1200

        per_agent = [r for r in summary["per_agent"] if r["agent_id"] == worker["id"]]
        assert per_agent, "worker missing from /api/tracking/summary per_agent"
        assert per_agent[0]["tokens"] == 1200

    def test_subagent_stop_marker_beats_misleading_agent_type(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """If the SubagentStop payload says agent_type='backend-worker' but the
        marker points at a frontend-worker, marker wins."""
        pid = marker_project["id"]
        fe = make_agent(
            project_id=pid, name="Freddie",
            role="frontend-worker", api_key="marker-wins-fe",
        )
        be = make_agent(
            project_id=pid, name="Barry",
            role="backend-worker", api_key="marker-wins-be",
        )
        _assign(client, pid, fe["id"])
        _assign(client, pid, be["id"])

        subagent_session_id = f"sub-wins-{uuid.uuid4()}"
        # Marker points at the frontend worker
        _write_marker(tmp_path, subagent_session_id, agent_id=fe["id"])

        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid-wins",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_session_id,
            # Payload lies: claims backend-worker
            "agent_type": "backend-worker",
            "agent_transcript_path": _write_transcript(
                tmp_path, name="freddie", input_tokens=10, output_tokens=5,
            ),
        })

        session = client.get(f"/api/hooks/sessions/{subagent_session_id}").json()
        assert session["agent_id"] == fe["id"], (
            f"marker said agent {fe['id']} (Freddie/frontend) but payload said "
            f"backend-worker and hook attributed to {session['agent_id']} — "
            f"marker was overridden"
        )


class TestSessionEndMarker:
    """Two flows: session-end arrives with no prior session-start (retroactive),
    and session-end arrives after a session-start that failed to resolve an agent."""

    def test_session_end_no_prior_start_resolves_via_marker(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """When session-end fires without a session-start, the handler creates the
        row from scratch — and must consult the marker first, not just the
        transcript / hook agent_name."""
        pid = marker_project["id"]
        target = make_agent(
            project_id=pid, name="Sage",
            role="tester", api_key="sess-end-late-sage",
        )
        _assign(client, pid, target["id"])

        sid = f"late-{uuid.uuid4()}"
        _write_marker(tmp_path, sid, agent_id=target["id"])

        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": str(tmp_path),
            "hook_event": "SessionEnd",
            # No prior start; transcript would resolve to something else if marker
            # were ignored, but the marker MUST be checked first.
            "transcript_path": _write_transcript(
                tmp_path, name="not-sage", input_tokens=50, output_tokens=25,
            ),
            "agent_name": "wrong-agent-name",
        })
        assert r.status_code == 200

        session = client.get(f"/api/hooks/sessions/{sid}").json()
        assert session["agent_id"] == target["id"]
        assert session["status"] == "completed"

    def test_session_end_reresolves_via_marker_when_start_had_no_agent(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """SessionStart fires before the marker is written (or the cwd was
        wrong). SessionEnd arrives later with the marker now present — the
        end-handler must re-resolve and update the hook_session row."""
        pid = marker_project["id"]
        target = make_agent(
            project_id=pid, name="Bolt",
            role="system-ops", api_key="sess-end-reresolve-bolt",
        )
        _assign(client, pid, target["id"])

        sid = f"reresolve-{uuid.uuid4()}"

        # Step 1: session-start with NO marker, NO agent_name. The TL fallback
        # may or may not fire depending on project assignment; either way we
        # don't have target attributed yet.
        client.post("/api/hooks/session-start", json={
            "session_id": sid,
            "cwd": str(tmp_path),
            "hook_event_name": "SessionStart",
        })

        # If start succeeded and resolved to anyone other than target, marker
        # at end-time should override. If start resolved to None, marker is
        # the first thing the re-resolve branch checks.
        before = client.get(f"/api/hooks/sessions/{sid}").json()
        # Sanity: we expect the row exists (handler doesn't fail-silently here)
        assert before["session_id"] == sid

        # Step 2: write marker, then fire session-end.
        _write_marker(tmp_path, sid, agent_id=target["id"])
        client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": str(tmp_path),
            "hook_event": "SessionEnd",
            "transcript_path": _write_transcript(
                tmp_path, name="bolt", input_tokens=20, output_tokens=10,
            ),
        })

        after = client.get(f"/api/hooks/sessions/{sid}").json()
        # The re-resolve branch (hook_tracking.py:240) only fires when
        # session.agent_id is NULL at end-time. If start happened to attribute
        # via TL-fallback, this assertion will be relaxed: we only require the
        # marker target to win when start left agent_id unset.
        if before.get("agent_id") is None:
            assert after["agent_id"] == target["id"], (
                "session_end re-resolve branch ignored the marker even though "
                "session-start left agent_id NULL"
            )
        else:
            # Document the behavior so future readers know this path is
            # intentionally untouched once an agent is already attributed.
            assert after["agent_id"] == before["agent_id"]


class TestSessionEndMarkerTokens:
    """End-to-end token landing on the SessionEnd path."""

    def test_session_end_marker_tokens_to_pm_overhead(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """PM role is OVERHEAD — tokens must land in pm_overhead_tokens, not on
        a ticket, even when the PM has tickets assigned to them. This is the
        exact regression DWB-294 was diagnosing for Pam."""
        pid = marker_project["id"]
        pm = make_agent(
            project_id=pid, name="Pam",
            role="pm", api_key="sess-end-pm-pam",
        )
        _assign(client, pid, pm["id"])

        sid = f"pm-end-{uuid.uuid4()}"
        _write_marker(tmp_path, sid, agent_id=pm["id"])

        r = client.post("/api/hooks/session-end", json={
            "session_id": sid,
            "cwd": str(tmp_path),
            "hook_event": "SessionEnd",
            "transcript_path": _write_transcript(
                tmp_path, name="pam", input_tokens=600, output_tokens=300,
            ),
        })
        assert r.status_code == 200

        summary = client.get(
            "/api/tracking/summary", params={"project_id": pid}
        ).json()
        # PM tokens count as overhead, not per_ticket
        assert summary["project_total"]["overhead_tokens"] == 900
        assert summary["per_ticket"] == [], (
            "PM tokens leaked onto per_ticket — overhead role should never "
            "attribute work to a ticket"
        )
        # DWB-306 (2026-06-05): per_agent rollup now includes overhead_token_report
        # events in addition to token_report. PM overhead correctly shows in
        # the `tokens` total, with an `overhead_tokens` breakdown.
        pam_entry = [r for r in summary["per_agent"] if r["agent_id"] == pm["id"]]
        assert pam_entry, "PM missing entirely from per_agent rollup"
        assert pam_entry[0]["tokens"] == 900, (
            "per_agent total should now include PM overhead tokens (DWB-306)"
        )
        assert pam_entry[0]["overhead_tokens"] == 900


# ---------------------------------------------------------------------------
# DWB-304 — pending-marker fallback
#
# CC's SubagentStop session_id is generated internally and can't be
# pre-computed by the spawning TL, so the TL pre-writes a "pending" marker
# keyed on agent identity. The resolver falls back to the oldest unconsumed
# pending marker for this project and atomically renames it to the actual
# session_id. These tests cover the new fallback path end-to-end.
# ---------------------------------------------------------------------------


def _write_pending_marker(
    repo_path,
    *,
    agent_id: int,
    project_id: int,
    unix_ms: int | None = None,
    rand: str = "a3f2",
    role: str = "backend-worker",
    agent_name: str = "Devin",
):
    """Write a pending-<agent_id>-<unix_ms>-<rand4hex> marker. Returns the path."""
    import time as _t
    if unix_ms is None:
        unix_ms = int(_t.time() * 1000)
    marker_dir = repo_path / ".claude" / "agents" / "active"
    marker_dir.mkdir(parents=True, exist_ok=True)
    name = f"pending-{agent_id}-{unix_ms}-{rand}"
    path = marker_dir / name
    path.write_text(json.dumps({
        "schema_version": 1,
        "agent_id": agent_id,
        "role": role,
        "agent_name": agent_name,
        "project_id": project_id,
        "spawned_at": "2026-06-05T13:45:00+00:00",
        "spawn_context": "pytest pending-marker fixture",
    }), encoding="utf-8")
    return path


class TestPendingMarkerFallback:
    """The TL writes pending-* markers before each Task() spawn; the resolver
    consumes the oldest one for this project when the literal session_id
    lookup misses. This is the path that fixes prod attribution."""

    def test_pending_marker_claimed_on_subagent_stop(
        self, client, marker_project, tmp_path, make_agent,
    ):
        pid = marker_project["id"]
        worker = make_agent(
            project_id=pid, name="Devin",
            role="backend-worker", api_key="pending-claim-devin",
        )
        _assign(client, pid, worker["id"])

        _write_pending_marker(
            tmp_path, agent_id=worker["id"], project_id=pid,
        )

        # CC fires SubagentStop with an internal hex session_id; no literal
        # marker file at that name exists.
        subagent_sid = f"ac{uuid.uuid4().hex[:15]}"

        r = client.post("/api/hooks/session-end", json={
            "session_id": "parent-real-cc-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_type": "",  # empty in real CC payloads (DWB-304 diag)
            "agent_transcript_path": _write_transcript(
                tmp_path, name="devin", input_tokens=300, output_tokens=200,
            ),
        })
        assert r.status_code == 200

        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        assert session["agent_id"] == worker["id"], (
            "pending marker was not consumed — fallback path failed"
        )

        # The pending marker should have been atomically renamed → session_id.
        marker_dir = tmp_path / ".claude" / "agents" / "active"
        leftover_pending = list(marker_dir.glob("pending-*"))
        assert leftover_pending == [], (
            f"pending marker not consumed (still on disk): {leftover_pending}"
        )
        assert (marker_dir / subagent_sid).is_file(), (
            "consumed marker should now be named for the session_id"
        )

    def test_oldest_pending_marker_wins(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """Two pending markers for the same role — oldest unix_ms wins."""
        pid = marker_project["id"]
        first = make_agent(
            project_id=pid, name="Devin",
            role="backend-worker", api_key="pending-first-devin",
        )
        second = make_agent(
            project_id=pid, name="Barry",
            role="backend-worker", api_key="pending-second-barry",
        )
        _assign(client, pid, first["id"])
        _assign(client, pid, second["id"])

        # First written has the smaller unix_ms.
        _write_pending_marker(
            tmp_path, agent_id=first["id"], project_id=pid,
            unix_ms=1000, rand="0001",
        )
        _write_pending_marker(
            tmp_path, agent_id=second["id"], project_id=pid,
            unix_ms=2000, rand="0002",
        )

        subagent_sid = f"ad{uuid.uuid4().hex[:15]}"
        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_transcript_path": _write_transcript(
                tmp_path, name="x", input_tokens=10, output_tokens=5,
            ),
        })

        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        assert session["agent_id"] == first["id"], (
            "oldest unix_ms pending marker should win — first spawn first served"
        )

        # The second pending marker is untouched, ready for the next claim.
        marker_dir = tmp_path / ".claude" / "agents" / "active"
        remaining = [p.name for p in marker_dir.glob("pending-*")]
        assert remaining == ["pending-{}-2000-0002".format(second["id"])], (
            f"second pending marker should still be on disk; got {remaining}"
        )

    def test_stale_pending_marker_garbage_collected(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """A pending marker with mtime > 1h old must be unlinked, not consumed."""
        pid = marker_project["id"]
        worker = make_agent(
            project_id=pid, name="Stale",
            role="backend-worker", api_key="pending-stale-worker",
        )
        _assign(client, pid, worker["id"])

        path = _write_pending_marker(
            tmp_path, agent_id=worker["id"], project_id=pid,
        )
        # Force mtime to ~2h ago.
        old = time.time() - 7200
        os.utime(path, (old, old))

        subagent_sid = f"ae{uuid.uuid4().hex[:15]}"
        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_transcript_path": _write_transcript(
                tmp_path, name="stale", input_tokens=10, output_tokens=5,
            ),
        })

        # Marker must be gone (GC'd), not consumed.
        marker_dir = tmp_path / ".claude" / "agents" / "active"
        assert not path.exists(), "stale pending marker should have been unlinked"
        assert not (marker_dir / subagent_sid).is_file(), (
            "stale marker must not be consumed onto a real session_id"
        )

        # The session falls through to the legacy resolve_agent path, so
        # attribution lands wherever that picks (TL fallback or similar).
        # The key assertion is that the stale marker did NOT win.
        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        assert session["agent_id"] != worker["id"], (
            "stale pending marker leaked attribution to its agent — GC failed"
        )

    def test_pending_marker_wrong_project_skipped(
        self, client, marker_project, tmp_path, make_agent, make_project,
    ):
        """A pending marker whose JSON says project_id=OTHER must not be claimed."""
        pid = marker_project["id"]
        other = make_project()  # different project_id, but written into our tmp_path
        worker = make_agent(
            project_id=pid, name="Right",
            role="backend-worker", api_key="pending-rightproj-worker",
        )
        _assign(client, pid, worker["id"])

        # Write a pending marker that CLAIMS to belong to the other project.
        _write_pending_marker(
            tmp_path, agent_id=worker["id"], project_id=other["id"],
        )

        subagent_sid = f"af{uuid.uuid4().hex[:15]}"
        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_transcript_path": _write_transcript(
                tmp_path, name="rightproj", input_tokens=10, output_tokens=5,
            ),
        })

        marker_dir = tmp_path / ".claude" / "agents" / "active"
        # Marker should still exist (untouched — wrong project, not claimed).
        leftover = list(marker_dir.glob("pending-*"))
        assert len(leftover) == 1, (
            "wrong-project pending marker must NOT be claimed"
        )
        assert not (marker_dir / subagent_sid).is_file()

    def test_literal_marker_wins_over_pending(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """When BOTH a literal session_id marker AND a pending marker exist,
        the literal wins — pending is reserved for the missing-literal path."""
        pid = marker_project["id"]
        literal_target = make_agent(
            project_id=pid, name="LiteralPaul",
            role="backend-worker", api_key="literal-wins-paul",
        )
        pending_target = make_agent(
            project_id=pid, name="PendingPete",
            role="backend-worker", api_key="literal-wins-pete",
        )
        _assign(client, pid, literal_target["id"])
        _assign(client, pid, pending_target["id"])

        subagent_sid = f"a0{uuid.uuid4().hex[:15]}"
        _write_marker(tmp_path, subagent_sid, agent_id=literal_target["id"])
        _write_pending_marker(
            tmp_path, agent_id=pending_target["id"], project_id=pid,
        )

        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_transcript_path": _write_transcript(
                tmp_path, name="literalpaul", input_tokens=10, output_tokens=5,
            ),
        })

        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        assert session["agent_id"] == literal_target["id"], (
            "literal session_id marker must win over pending fallback"
        )

        # Pending marker must still be on disk — never touched.
        marker_dir = tmp_path / ".claude" / "agents" / "active"
        leftover_pending = list(marker_dir.glob("pending-*"))
        assert len(leftover_pending) == 1, (
            "pending marker should be untouched when literal wins"
        )


# ---------------------------------------------------------------------------
# DWB-390 - agent_id-aware pending-marker claim
#
# The DWB-304 FIFO selection works fine when only one agent's pending marker
# is in the dir, but when several pending markers from a single TL spawn batch
# coexist and concurrent SubagentStops race the claim, FIFO can stamp one
# agent's session_id onto another agent's pending marker - misattribution by
# luck of timing. When the hook payload carries an identity hint
# (agent_type / agent_name) the resolver should claim only the marker whose
# agent_id matches the hint. No hint -> legacy FIFO is preserved.
# ---------------------------------------------------------------------------


class TestPendingMarkerAgentIdHint:

    def test_agent_type_hint_claims_matching_pending(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """Two pending markers for different agents. Subagent stop carries
        agent_type that resolves to the SECOND-in-time agent. Verify the
        SECOND pending is claimed (not the FIFO-oldest)."""
        pid = marker_project["id"]
        # First-by-unix_ms agent (would win under FIFO).
        first_agent = make_agent(
            project_id=pid, name="FifoLoser",
            role="frontend-worker", api_key="hint-fifo-loser",
        )
        # Second-by-unix_ms agent (matches the hint).
        target = make_agent(
            project_id=pid, name="HintWinner",
            role="backend-worker", api_key="hint-target",
        )
        _assign(client, pid, first_agent["id"])
        _assign(client, pid, target["id"])

        _write_pending_marker(
            tmp_path, agent_id=first_agent["id"], project_id=pid,
            unix_ms=1000, rand="0001", role="frontend-worker",
            agent_name="FifoLoser",
        )
        _write_pending_marker(
            tmp_path, agent_id=target["id"], project_id=pid,
            unix_ms=2000, rand="0002", role="backend-worker",
            agent_name="HintWinner",
        )

        subagent_sid = f"b1{uuid.uuid4().hex[:15]}"
        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_type": "backend-worker",
            "agent_transcript_path": _write_transcript(
                tmp_path, name="hintwinner", input_tokens=10, output_tokens=5,
            ),
        })

        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        assert session["agent_id"] == target["id"], (
            "agent_type hint should override FIFO selection - target agent "
            f"({target['id']}) must win, got agent_id={session['agent_id']}"
        )

        # Target's pending marker consumed; first agent's marker still on disk.
        marker_dir = tmp_path / ".claude" / "agents" / "active"
        remaining = sorted(p.name for p in marker_dir.glob("pending-*"))
        assert remaining == [f"pending-{first_agent['id']}-1000-0001"], (
            f"only the non-matching pending should remain; got {remaining}"
        )
        assert (marker_dir / subagent_sid).is_file(), (
            "target's pending should have been renamed to the session_id"
        )

    def test_agent_type_hint_no_match_refuses_claim(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """Pending marker exists for agent X. SubagentStop carries agent_type
        resolving to agent Y (no pending for Y). The resolver must NOT claim
        X's marker - misattribution-by-luck is exactly the bug to fix."""
        pid = marker_project["id"]
        unrelated = make_agent(
            project_id=pid, name="UnrelatedPending",
            role="frontend-worker", api_key="hint-unrelated",
        )
        hinted = make_agent(
            project_id=pid, name="HintHasNoMarker",
            role="backend-worker", api_key="hint-no-marker",
        )
        _assign(client, pid, unrelated["id"])
        _assign(client, pid, hinted["id"])

        _write_pending_marker(
            tmp_path, agent_id=unrelated["id"], project_id=pid,
            role="frontend-worker", agent_name="UnrelatedPending",
        )

        subagent_sid = f"b2{uuid.uuid4().hex[:15]}"
        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_type": "backend-worker",  # resolves to hinted, no pending for it
            "agent_transcript_path": _write_transcript(
                tmp_path, name="nopending", input_tokens=10, output_tokens=5,
            ),
        })

        # Unrelated's marker must still be on disk - the resolver refused to
        # claim a marker whose agent_id didn't match the hint.
        marker_dir = tmp_path / ".claude" / "agents" / "active"
        remaining = list(marker_dir.glob("pending-*"))
        assert len(remaining) == 1, (
            "non-matching pending must not be claimed when hint is unambiguous"
        )

        # The session falls through to the legacy resolve_agent path. agent_type
        # = "backend-worker" matches `hinted` by role, so attribution still lands
        # on the right agent - the marker just didn't help.
        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        assert session["agent_id"] == hinted["id"], (
            "legacy resolve_agent should still match by role when marker miss"
        )

    def test_no_hint_preserves_fifo_when_payload_has_no_agent_type(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """Backstop: DWB-304 FIFO behaviour preserved when the payload carries
        no agent_type / agent_name (older CC clients, transcript-only flows)."""
        pid = marker_project["id"]
        first = make_agent(
            project_id=pid, name="NoHintFirst",
            role="backend-worker", api_key="no-hint-first",
        )
        second = make_agent(
            project_id=pid, name="NoHintSecond",
            role="backend-worker", api_key="no-hint-second",
        )
        _assign(client, pid, first["id"])
        _assign(client, pid, second["id"])

        _write_pending_marker(
            tmp_path, agent_id=first["id"], project_id=pid,
            unix_ms=3000, rand="0003",
        )
        _write_pending_marker(
            tmp_path, agent_id=second["id"], project_id=pid,
            unix_ms=4000, rand="0004",
        )

        subagent_sid = f"b3{uuid.uuid4().hex[:15]}"
        # No agent_type / agent_name in the payload -> hint is None.
        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_transcript_path": _write_transcript(
                tmp_path, name="nohint", input_tokens=10, output_tokens=5,
            ),
        })

        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        assert session["agent_id"] == first["id"], (
            "no-hint payload should fall back to FIFO (oldest unix_ms wins)"
        )


# =====================================================================
# DWB-311 — SubagentStop production transcript-path regression
# =====================================================================
#
# Original symptom (pre-fix, dev DB rows 190–192 on 2026-06-05): 124
# SubagentStop rows for project_id=1 with total_tokens=0 even when the
# marker resolved the correct agent. Claude Code sends
# `agent_transcript_path` pointing at a synthetic path inside a
# `subagents/` subdirectory that does not exist on disk:
#
#   /.../<project>/<parent_uuid>/subagents/agent-<subagent_sid>.jsonl
#                              ^^^^^^^^^^^^
#                              no such directory
#
# The actual subagent transcript content is interleaved INSIDE the
# project's per-session `.jsonl` files, each line carrying an
# `agentName` field identifying the subagent. The fix in
# `_handle_subagent_stop` (hook_tracking.py): when the primary
# parse_transcript returns 0 AND the synthetic file is absent, walk the
# project's `.jsonl` siblings and accumulate usage filtered by the
# resolved agent's name. See `_parse_subagent_from_projects_dir`.
#
# These tests pin the OUTCOME, not the mechanism: when a subagent did
# real work, the resulting hook_session row must carry total_tokens > 0
# and the breakdown must match the actual usage.


class TestSubagentStopProductionTranscriptPath:
    """DWB-311 regression — SubagentStop tokens must land even when
    the hook's agent_transcript_path points at a synthetic, non-existent
    `subagents/agent-<sid>.jsonl` path (production reality)."""

    def _build_realistic_cc_transcript(
        self,
        tmp_path,
        *,
        parent_uuid: str,
        subagent_sid: str,
        agent_name: str,
        usage_messages: list,
    ) -> tuple[str, str]:
        """Returns (synthetic_agent_transcript_path_that_doesnt_exist,
        parent_session_jsonl_path_that_does_exist).

        Mirrors the on-disk layout CC actually produces:
          /<projects>/<project>/<parent_uuid>.jsonl    ← REAL content
          /<projects>/<project>/<parent_uuid>/subagents/agent-<sid>.jsonl
                                              ← hook reports THIS path; it
                                                doesn't exist on disk.

        The parent JSONL contains interleaved lines tagged with
        agentName=<agent_name> + nested message.usage (real CC format).
        """
        projects_root = tmp_path / "claude_projects"
        project_dir = projects_root / "-test-project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Write the parent transcript with realistic CC line shape.
        parent_jsonl = project_dir / f"{parent_uuid}.jsonl"
        lines = []
        for u in usage_messages:
            lines.append(json.dumps({
                "parentUuid": str(uuid.uuid4()),
                "isSidechain": False,
                "agentName": agent_name,
                "subagentSessionId": subagent_sid,
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "type": "message",
                    "usage": {
                        "input_tokens": u.get("input_tokens", 0),
                        "output_tokens": u.get("output_tokens", 0),
                        "cache_creation_input_tokens": u.get(
                            "cache_creation_input_tokens", 0
                        ),
                        "cache_read_input_tokens": u.get(
                            "cache_read_input_tokens", 0
                        ),
                    },
                },
            }))
        parent_jsonl.write_text("\n".join(lines) + "\n")

        # Synthetic path the hook reports — DELIBERATELY not created.
        synthetic_path = str(
            project_dir / parent_uuid / "subagents" / f"agent-{subagent_sid}.jsonl"
        )
        return synthetic_path, str(parent_jsonl)

    def test_subagent_stop_tokens_land_when_transcript_path_is_synthetic(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """Production scenario: hook reports a synthetic path. Tokens must
        still land in hook_session.total_tokens because real work was done.
        """
        pid = marker_project["id"]
        worker = make_agent(
            project_id=pid, name="Barry-311",
            role="backend-worker", api_key="dwb-311-prod-path",
        )
        _assign(client, pid, worker["id"])

        parent_uuid = str(uuid.uuid4())
        subagent_sid = f"a{uuid.uuid4().hex[:16]}"  # CC-style: hex string
        _write_marker(tmp_path, subagent_sid, agent_id=worker["id"])

        synthetic_path, _real_parent_path = self._build_realistic_cc_transcript(
            tmp_path,
            parent_uuid=parent_uuid,
            subagent_sid=subagent_sid,
            agent_name="Barry-311",
            usage_messages=[
                {"input_tokens": 500, "output_tokens": 200},
                {"input_tokens": 800, "output_tokens": 300,
                 "cache_read_input_tokens": 100},
            ],
        )

        # Sanity: the synthetic path the hook reports does NOT exist.
        assert not os.path.exists(synthetic_path), (
            "synthetic path must not exist — that's the production bug we're testing"
        )

        r = client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid-for-311",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_type": "backend-worker",
            "agent_transcript_path": synthetic_path,
        })
        assert r.status_code == 200

        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        # Total tokens from the realistic transcript: 500+200 + 800+300+100 = 1900
        assert session["total_tokens"] > 0, (
            f"SubagentStop with real work must persist nonzero tokens; "
            f"got {session['total_tokens']}"
        )

    def test_subagent_stop_with_real_cc_shape_lands_token_breakdown(
        self, client, marker_project, tmp_path, make_agent,
    ):
        """Stronger contract: not just total_tokens > 0, but the breakdown
        sums to the actual input/output/cache counts so downstream
        attribution per category is preserved."""
        pid = marker_project["id"]
        worker = make_agent(
            project_id=pid, name="Barry-311-breakdown",
            role="backend-worker", api_key="dwb-311-breakdown",
        )
        _assign(client, pid, worker["id"])

        parent_uuid = str(uuid.uuid4())
        subagent_sid = f"a{uuid.uuid4().hex[:16]}"
        _write_marker(tmp_path, subagent_sid, agent_id=worker["id"])

        synthetic_path, _ = self._build_realistic_cc_transcript(
            tmp_path,
            parent_uuid=parent_uuid,
            subagent_sid=subagent_sid,
            agent_name="Barry-311-breakdown",
            usage_messages=[
                {"input_tokens": 1000, "output_tokens": 500,
                 "cache_creation_input_tokens": 200,
                 "cache_read_input_tokens": 50},
            ],
        )

        client.post("/api/hooks/session-end", json={
            "session_id": "parent-sid-311-breakdown",
            "cwd": str(tmp_path),
            "hook_event_name": "SubagentStop",
            "agent_id": subagent_sid,
            "agent_type": "backend-worker",
            "agent_transcript_path": synthetic_path,
        })

        session = client.get(f"/api/hooks/sessions/{subagent_sid}").json()
        # 1000+500+200+50 = 1750
        assert session["total_tokens"] == 1750, (
            f"breakdown should sum exactly to 1750: got {session['total_tokens']}"
        )
        breakdown = session.get("token_breakdown") or {}
        assert breakdown.get("input") == 1000
        assert breakdown.get("output") == 500
        assert breakdown.get("cache_creation") == 200
        assert breakdown.get("cache_read") == 50
