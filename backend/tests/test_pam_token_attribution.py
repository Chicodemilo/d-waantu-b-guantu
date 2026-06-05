# Path: tests/test_pam_token_attribution.py
# File: test_pam_token_attribution.py
# Created: 2026-06-04
# Purpose: DWB-300 — verify PM token attribution end-to-end post DWB-294 marker fix.
#          Baseline showed Pam=50 tokens despite being on every team; this test
#          locks in correct behavior + surfaces the per_agent overhead gap.
# Caller: pytest
# Callees: POST /api/hooks/session-end, GET /api/tracking/summary
# Data In: tmp_path-rooted .claude/agents/active/<sid> markers, fake JSONL transcripts
# Data Out: Assertions on project_total.overhead_tokens, project.pm_overhead_tokens,
#           per_agent rollup behavior, PM-vs-TL ratio
# Last Modified: 2026-06-04

"""DWB-300 — Pam (PM) token attribution verification.

Background: Pam was tracking 50 tokens total despite being on every team.
DWB-294 fixed the marker-resolution path. This file proves that with a
correct marker:

  1. PM session tokens reach project_total.overhead_tokens (project-level)
  2. PM session tokens reach project.pm_overhead_tokens (PM-specific bucket)
  3. PM tokens do NOT land on tickets (overhead role contract)
  4. TL and PM markers attribute independently (no cross-contamination)

DWB-306 (2026-06-05) fixed the per_agent rollup: it now aggregates both
token_report AND overhead_token_report events. The `tokens` field is the
total, and a new `overhead_tokens` field provides the overhead breakdown.
Test test_pm_tokens_invisible_in_per_agent_rollup has been updated to
assert the corrected behavior (was an inversion-instruction failure).
"""

import json
import uuid

import pytest


def _write_marker(repo_path, session_id, *, agent_id: int):
    marker_dir = repo_path / ".claude" / "agents" / "active"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / session_id).write_text(
        json.dumps({"agent_id": agent_id}), encoding="utf-8"
    )


def _write_transcript(tmp_path, *, name: str, input_tokens: int, output_tokens: int) -> str:
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
def pm_project(client, make_project, tmp_path):
    return make_project(repo_path=str(tmp_path))


def _assign(client, project_id, agent_id):
    r = client.post("/api/project-agents", json={
        "project_id": project_id, "agent_id": agent_id,
    })
    assert r.status_code == 201


def _drive_pm_session(client, project, tmp_path, pm, *, input_tokens, output_tokens):
    """Fake one full PM SessionEnd with marker → return summary."""
    sid = f"pam-{uuid.uuid4()}"
    _write_marker(tmp_path, sid, agent_id=pm["id"])
    client.post("/api/hooks/session-end", json={
        "session_id": sid,
        "cwd": str(tmp_path),
        "hook_event": "SessionEnd",
        "transcript_path": _write_transcript(
            tmp_path, name="pam",
            input_tokens=input_tokens, output_tokens=output_tokens,
        ),
    })
    return client.get(
        "/api/tracking/summary", params={"project_id": project["id"]}
    ).json()


class TestPamProjectLevelAttribution:
    """Project-level totals are the source of truth — these must be correct."""

    def test_pm_tokens_land_in_project_total_overhead(
        self, client, pm_project, tmp_path, make_agent,
    ):
        pm = make_agent(
            project_id=pm_project["id"], name="Pam",
            role="pm", api_key="pam-attr-1",
        )
        _assign(client, pm_project["id"], pm["id"])

        summary = _drive_pm_session(
            client, pm_project, tmp_path, pm,
            input_tokens=2000, output_tokens=1000,
        )
        assert summary["project_total"]["overhead_tokens"] == 3000
        # Sanity: PM tokens never produce a per_ticket row
        assert summary["per_ticket"] == []

    def test_pm_tokens_land_in_pm_overhead_bucket_not_tl(
        self, client, pm_project, tmp_path, make_agent,
    ):
        """The project model has two overhead buckets: pm_overhead_tokens and
        tl_overhead_tokens. PM hits the PM bucket — proves the bucket split
        added in hook_tracking.py respects role."""
        pm = make_agent(
            project_id=pm_project["id"], name="Pam",
            role="pm", api_key="pam-bucket",
        )
        _assign(client, pm_project["id"], pm["id"])

        _drive_pm_session(
            client, pm_project, tmp_path, pm,
            input_tokens=500, output_tokens=250,
        )
        # Refresh the project from the API
        p = client.get(f"/api/projects/{pm_project['id']}").json()
        assert p.get("pm_overhead_tokens", 0) == 750, (
            f"PM tokens did not land in pm_overhead_tokens bucket: "
            f"got {p.get('pm_overhead_tokens')}, expected 750"
        )
        assert p.get("tl_overhead_tokens", 0) == 0, (
            "PM tokens leaked into tl_overhead_tokens bucket"
        )

    def test_pm_session_never_creates_ticket_attribution(
        self, client, pm_project, tmp_path, make_agent,
        make_epic, make_sprint, make_ticket,
    ):
        """Even when the PM has an in_progress ticket assigned (common — PMs
        often have audit/admin tickets), their session tokens MUST go to
        overhead, not the ticket."""
        pid = pm_project["id"]
        pm = make_agent(
            project_id=pid, name="Pam",
            role="pm", api_key="pam-no-ticket-attr",
        )
        _assign(client, pid, pm["id"])
        epic = make_epic(project_id=pid)
        sprint = make_sprint(project_id=pid, epic_id=epic["id"])
        ticket = make_ticket(
            project_id=pid, sprint_id=sprint["id"],
            assigned_agent_id=pm["id"], status="in_progress",
            title="Audit alerts",
        )

        _drive_pm_session(
            client, pm_project, tmp_path, pm,
            input_tokens=400, output_tokens=200,
        )
        # PM's ticket should remain at 0 tokens — overhead role bypasses
        # ticket attribution by design.
        t = client.get(f"/api/tickets/{ticket['id']}").json()
        assert t["tokens_used"] == 0, (
            f"PM tokens leaked onto ticket {t['ticket_key']}: "
            f"{t['tokens_used']} tokens. Overhead roles must NEVER attribute "
            f"to tickets — even when one is assigned to them."
        )


class TestPamVsTlIndependence:
    """DWB-300 explicitly asks for a PM:TL ratio. To compute one, PM and TL
    attribution must be independent. These tests fence off cross-contamination."""

    def test_pm_and_tl_attribute_to_separate_buckets(
        self, client, pm_project, tmp_path, make_agent,
    ):
        pid = pm_project["id"]
        pm = make_agent(
            project_id=pid, name="Pam", role="pm", api_key="indep-pm",
        )
        tl = make_agent(
            project_id=pid, name="Archie", role="team-lead",
            api_key="indep-tl",
        )
        _assign(client, pid, pm["id"])
        _assign(client, pid, tl["id"])

        # Drive PM session: 3000 overhead tokens
        _drive_pm_session(
            client, pm_project, tmp_path, pm,
            input_tokens=2000, output_tokens=1000,
        )
        # Drive TL session: 7000 overhead tokens
        sid_tl = f"tl-{uuid.uuid4()}"
        _write_marker(tmp_path, sid_tl, agent_id=tl["id"])
        client.post("/api/hooks/session-end", json={
            "session_id": sid_tl,
            "cwd": str(tmp_path),
            "hook_event": "SessionEnd",
            "transcript_path": _write_transcript(
                tmp_path, name="archie",
                input_tokens=5000, output_tokens=2000,
            ),
        })

        p = client.get(f"/api/projects/{pid}").json()
        assert p.get("pm_overhead_tokens", 0) == 3000
        assert p.get("tl_overhead_tokens", 0) == 7000

        # Ratio is computable for DWB-300 reporting
        ratio = p["pm_overhead_tokens"] / p["tl_overhead_tokens"]
        # Just sanity — 3000/7000 ~ 0.43. The test isn't pinning a "good" ratio,
        # only that division is defined and produces a sane fraction.
        assert 0.0 < ratio < 10.0


class TestPerAgentRollupGap:
    """DOCUMENTS the known gap: per_agent doesn't include overhead tokens.

    This is the actual mechanism behind 'Pam shows 0 in the dashboard'.
    The marker fix (DWB-294) correctly attributes overhead — but the
    /api/tracking/summary per_agent query filters by 'token_report' only.
    The day someone fixes the rollup, this test fails and signals that
    DWB-300 should be re-evaluated.
    """

    def test_pm_tokens_invisible_in_per_agent_rollup(
        self, client, pm_project, tmp_path, make_agent,
    ):
        pm = make_agent(
            project_id=pm_project["id"], name="Pam",
            role="pm", api_key="rollup-gap-pm",
        )
        _assign(client, pm_project["id"], pm["id"])

        summary = _drive_pm_session(
            client, pm_project, tmp_path, pm,
            input_tokens=1500, output_tokens=500,
        )
        # Overhead total = 2000 (this part is correct)
        assert summary["project_total"]["overhead_tokens"] == 2000

        # DWB-306 (2026-06-05): per_agent now aggregates BOTH token_report
        # and overhead_token_report. The `tokens` field is the total, the
        # `overhead_tokens` field is the breakdown of the overhead portion.
        # See tracking.py get_project_summary().
        pam_entry = [r for r in summary["per_agent"] if r["agent_id"] == pm["id"]]
        assert pam_entry, "PM missing entirely from per_agent rollup"
        assert pam_entry[0]["tokens"] == 2000, (
            "per_agent total should include PM overhead tokens"
        )
        assert pam_entry[0]["overhead_tokens"] == 2000, (
            "per_agent overhead_tokens breakdown should equal the PM overhead total"
        )
