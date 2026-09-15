# Path: tests/test_attribution_anomalies_dwb539.py
# File: test_attribution_anomalies_dwb539.py
# Created: 2026-09-15
# Purpose: DWB-539 regression: the three session-109 attribution anomalies. Worker time comes from the transcript span instead of collapsing to 0, abandoned hook sessions stop claiming a whole window they never worked, and hook token attribution no longer lands on a stale closed-sprint ticket.
# Caller: pytest
# Callees: app.services.hook_tracking (_parse_transcript_lines, _resolve_ticket, _as_naive_utc), app.services.dwb_session_rollup.compute_by_role
# Data In: Synthetic transcript lines, factory project/sprint/ticket/agent rows, hand-built HookSession rows
# Data Out: Assertions on parsed spans, rollup time_seconds, and resolved ticket identity
# Last Modified: 2026-09-15 (DWB-539)

"""DWB-539: impossible ratios were the tell that time and tokens keyed differently.

Session 109 showed Barry_DWB with 12.3M tokens and 1 second, Stan 8.4M and 0s,
and a dark Sage with 0 tokens holding 46768s, the whole session. Three
independent causes, one regression test class each.
"""

import io
import json
from datetime import datetime, timedelta

import pytest

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.hook_session import HookSession, HookSessionStatus
from app.models.ticket import Ticket, TicketStatus
from app.services import dwb_session_rollup as rollup
from app.services import hook_tracking as hooks


def _usage_line(ts, *, tokens=100, agent_name=None):
    entry = {
        "timestamp": ts,
        "message": {"usage": {
            "input_tokens": tokens, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        }},
    }
    if agent_name:
        entry["agentName"] = agent_name
    return json.dumps(entry)


# ---------------------------------------------------------------------------
# Cause 1: the row's interval ran backwards, so every duration clamped to 0
# ---------------------------------------------------------------------------


class TestTranscriptSpan:
    def test_parse_returns_first_and_last_timestamp(self):
        lines = io.StringIO("\n".join([
            _usage_line("2026-09-15T14:30:00Z"),
            _usage_line("2026-09-15T14:35:00Z"),
            _usage_line("2026-09-15T14:42:00Z"),
        ]))
        parsed = hooks._parse_transcript_lines(lines)
        assert parsed["start_time"].hour == 14 and parsed["start_time"].minute == 30
        assert parsed["end_time"].hour == 14 and parsed["end_time"].minute == 42

    def test_out_of_order_lines_still_bound_the_span(self):
        lines = io.StringIO("\n".join([
            _usage_line("2026-09-15T14:42:00Z"),
            _usage_line("2026-09-15T14:30:00Z"),
        ]))
        parsed = hooks._parse_transcript_lines(lines)
        assert parsed["start_time"] < parsed["end_time"]

    def test_missing_transcript_reports_no_span(self):
        parsed = hooks.parse_transcript("/nonexistent/transcript.jsonl")
        assert parsed["start_time"] is None
        assert parsed["end_time"] is None

    def test_naive_utc_normalizer(self):
        aware = datetime.fromisoformat("2026-09-15T14:30:00+00:00")
        assert hooks._as_naive_utc(aware).tzinfo is None
        naive = datetime(2026, 9, 15, 14, 30)
        assert hooks._as_naive_utc(naive) == naive
        assert hooks._as_naive_utc(None) is None


# ---------------------------------------------------------------------------
# Cause 2: an abandoned hook session claimed the entire window it never worked
# ---------------------------------------------------------------------------


@pytest.fixture
def rollup_world(client, db_session, make_project, make_agent):
    project = make_project()
    pid = project["id"]
    worker = make_agent(project_id=pid, name="RollupWorker",
                        role="backend-worker", api_key="rb-worker")
    dark = make_agent(project_id=pid, name="RollupDark",
                      role="tester", api_key="rb-dark")
    opened = datetime(2026, 9, 15, 4, 0, 0)
    # is_open is a generated column; never assign it. open_method is NOT NULL.
    session = DwbSession(project_id=pid, opened_at=opened,
                         closed_at=opened + timedelta(hours=13),
                         open_method=DwbOpenMethod.regex)
    db_session.add(session)
    db_session.flush()

    def add_hook(agent_id, start, end, tokens, *, status=HookSessionStatus.completed):
        row = HookSession(
            session_id=f"hs-{agent_id}-{start.isoformat()}",
            agent_id=agent_id, project_id=pid, start_time=start, end_time=end,
            total_tokens=tokens, status=status, dwb_session_id=session.id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return {"pid": pid, "session": session, "worker": worker["id"],
            "dark": dark["id"], "opened": opened, "add_hook": add_hook}


class TestAbandonedSessionsExcluded:
    def test_stale_open_session_no_longer_claims_the_window(
        self, db_session, rollup_world,
    ):
        """The dark-Sage case: a months-old hook row that never got an end_time
        used to be treated as still running and clamped to the whole window."""
        w = rollup_world
        w["add_hook"](w["dark"], datetime(2026, 4, 16, 19, 20), None, 0,
                      status=HookSessionStatus.active)
        by_role = rollup.compute_by_role(db_session, w["session"])
        dark = [r for r in by_role if r["agent_id"] == w["dark"]]
        assert dark == [] or dark[0]["time_seconds"] == 0

    def test_session_opened_inside_the_window_still_counts_as_running(
        self, db_session, rollup_world,
    ):
        """A genuinely in-flight session is not collateral damage: it started
        inside the window, so it still runs to the window end."""
        w = rollup_world
        w["add_hook"](w["worker"], w["opened"] + timedelta(hours=1), None, 5000,
                      status=HookSessionStatus.active)
        by_role = rollup.compute_by_role(db_session, w["session"])
        worker = [r for r in by_role if r["agent_id"] == w["worker"]][0]
        assert worker["time_seconds"] > 0

    def test_worker_time_tracks_their_hook_sessions(self, db_session, rollup_world):
        """AC: worker time_seconds tracks their hook sessions. Two closed spans
        of 600s and 300s roll up to 900s, not 0 and not the whole window."""
        w = rollup_world
        base = w["opened"] + timedelta(hours=2)
        w["add_hook"](w["worker"], base, base + timedelta(seconds=600), 1_200_000)
        w["add_hook"](w["worker"], base + timedelta(hours=1),
                      base + timedelta(hours=1, seconds=300), 800_000)
        worker = [r for r in rollup.compute_by_role(db_session, w["session"])
                  if r["agent_id"] == w["worker"]][0]
        assert worker["tokens"] == 2_000_000
        assert worker["time_seconds"] == 900

    def test_token_heavy_agent_is_never_zero_seconds(self, db_session, rollup_world):
        """The headline anomaly: millions of tokens against ~0 seconds."""
        w = rollup_world
        base = w["opened"] + timedelta(hours=3)
        w["add_hook"](w["worker"], base, base + timedelta(seconds=754), 12_300_000)
        worker = [r for r in rollup.compute_by_role(db_session, w["session"])
                  if r["agent_id"] == w["worker"]][0]
        assert worker["tokens"] == 12_300_000
        assert worker["time_seconds"] == 754


# ---------------------------------------------------------------------------
# Cause 3: hook attribution reached across sprints onto a stale ticket
# ---------------------------------------------------------------------------


@pytest.fixture
def sprint_world(client, db_session, make_project, make_agent, make_epic):
    project = make_project()
    pid = project["id"]
    agent = make_agent(project_id=pid, name="SprintWorker",
                       role="backend-worker", api_key="sw-worker")
    epic = make_epic(project_id=pid)
    old = client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "old sprint",
        "sprint_number": 1, "status": "completed",
    }).json()
    active = client.post("/api/sprints", json={
        "project_id": pid, "epic_id": epic["id"], "goal": "current sprint",
        "sprint_number": 2, "status": "active",
    }).json()

    counter = [0]

    def add_ticket(sprint_id, status):
        counter[0] += 1
        t = client.post("/api/tickets", json={
            "project_id": pid, "sprint_id": sprint_id, "epic_id": epic["id"],
            "ticket_key": f"SW-{counter[0]}", "title": f"ticket {counter[0]}",
            "assigned_agent_id": agent["id"],
        }).json()
        row = db_session.get(Ticket, t["id"])
        row.status = status
        db_session.flush()
        return row

    return {"pid": pid, "agent_id": agent["id"], "old": old["id"],
            "active": active["id"], "add": add_ticket}


class TestTicketScopedToActiveSprint:
    def _agent(self, db_session, sprint_world):
        from app.models.agent import Agent
        return db_session.get(Agent, sprint_world["agent_id"])

    def test_stale_in_progress_on_closed_sprint_is_not_chosen(
        self, db_session, sprint_world,
    ):
        """The exact S81 failure: a sprint-158 ticket left in_progress swallowed
        the tokens of sprint-160 work."""
        w = sprint_world
        stale = w["add"](w["old"], TicketStatus.in_progress)
        current = w["add"](w["active"], TicketStatus.in_progress)
        resolved = hooks._resolve_ticket(
            db_session, self._agent(db_session, w), w["pid"],
        )
        assert resolved is not None
        assert resolved.id == current.id
        assert resolved.id != stale.id

    def test_in_review_current_beats_in_progress_stale(self, db_session, sprint_world):
        """A worker flips to in_review before the hook fires; the current
        sprint's in_review ticket must still win over a stale in_progress."""
        w = sprint_world
        w["add"](w["old"], TicketStatus.in_progress)
        current = w["add"](w["active"], TicketStatus.in_review)
        resolved = hooks._resolve_ticket(
            db_session, self._agent(db_session, w), w["pid"],
        )
        assert resolved.id == current.id

    def test_no_current_sprint_ticket_returns_none_not_a_stale_one(
        self, db_session, sprint_world,
    ):
        """Better unattributed (the ad_hoc bucket) than attributed to the wrong
        ticket: a wrong ticket corrupts two numbers at once."""
        w = sprint_world
        w["add"](w["old"], TicketStatus.in_progress)
        resolved = hooks._resolve_ticket(
            db_session, self._agent(db_session, w), w["pid"],
        )
        assert resolved is None

    def test_project_without_active_sprint_keeps_old_behavior(
        self, client, db_session, sprint_world,
    ):
        """No active sprint means no scope to apply; projects that do not run
        sprints must not regress into permanent non-attribution."""
        w = sprint_world
        client.patch(f"/api/sprints/{w['active']}", json={"status": "completed"})
        only = w["add"](w["old"], TicketStatus.in_progress)
        resolved = hooks._resolve_ticket(
            db_session, self._agent(db_session, w), w["pid"],
        )
        assert resolved is not None and resolved.id == only.id
