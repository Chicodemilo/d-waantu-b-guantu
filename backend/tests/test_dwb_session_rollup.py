# Path: tests/test_dwb_session_rollup.py
# File: test_dwb_session_rollup.py
# Created: 2026-06-09
# Purpose: Tests for the DWB session list + detail rollup endpoints (DWB-338)
# Caller: pytest
# Callees: app.routers.dwb_sessions GET endpoints, app.services.dwb_session_rollup
# Data In: per-test db_session, factory fixtures, hand-rolled hook_session + tracking_log rows
# Data Out: Assertions on endpoint shape, status codes, rollup math
# Last Modified: 2026-06-09

"""Coverage for the read endpoints added in DWB-338:

- GET /api/projects/{id}/sessions   — list, most-recent first, status field
- GET /api/sessions/{id}             — full detail with by_role + by_ticket
                                       + tl/pm overhead + live flag

Sylvie's DWB-336 lifecycle (POST open / POST close) lives in
test_dwb_sessions.py (matches the router stem to keep the test-coverage
gate green). The DWB-338 tests live here so the two scopes don't collide
during the parallel review pass.
"""

from datetime import datetime, timedelta

import pytest

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.tracking_log import TrackingLog


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def insert_dwb_session(db_session):
    """Insert a DwbSession directly via the per-test session."""

    def _make(
        project_id,
        *,
        opened_offset_minutes,
        closed_offset_minutes=None,
        total_tokens=0,
        total_time_seconds=0,
        open_method=DwbOpenMethod.regex,
        close_method=None,
        close_reason=None,
        open_phrase=None,
        close_phrase=None,
    ):
        now = _naive_now()
        row = DwbSession(
            project_id=project_id,
            opened_at=now - timedelta(minutes=opened_offset_minutes),
            closed_at=(
                None
                if closed_offset_minutes is None
                else now - timedelta(minutes=closed_offset_minutes)
            ),
            open_method=open_method,
            close_method=close_method,
            close_reason=close_reason,
            open_phrase=open_phrase,
            close_phrase=close_phrase,
            total_tokens=total_tokens,
            total_time_seconds=total_time_seconds,
        )
        db_session.add(row)
        db_session.flush()
        db_session.refresh(row)
        return row

    return _make


@pytest.fixture
def insert_hook_session(db_session):
    def _make(
        project_id,
        *,
        session_id,
        agent_id,
        start_offset_minutes,
        end_offset_minutes=None,
        total_tokens=0,
        dwb_session_id=None,
    ):
        now = _naive_now()
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            agent_id=agent_id,
            start_time=now - timedelta(minutes=start_offset_minutes),
            end_time=(
                None
                if end_offset_minutes is None
                else now - timedelta(minutes=end_offset_minutes)
            ),
            status=HookSessionStatus.completed
            if end_offset_minutes is not None
            else HookSessionStatus.active,
            session_type=HookSessionType.teammate,
            total_tokens=total_tokens,
            dwb_session_id=dwb_session_id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture
def insert_tracking(db_session):
    def _make(
        *,
        project_id,
        agent_id,
        ticket_id=None,
        event_type,
        offset_minutes,
        tokens=0,
    ):
        row = TrackingLog(
            project_id=project_id,
            agent_id=agent_id,
            ticket_id=ticket_id,
            sprint_id=None,
            event_type=event_type,
            tokens=tokens,
            timestamp=_naive_now() - timedelta(minutes=offset_minutes),
            source="test",
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/sessions
# ---------------------------------------------------------------------------


class TestListProjectSessions:
    def test_returns_most_recent_first(
        self, client, make_project, insert_dwb_session
    ):
        project = make_project()
        oldest = insert_dwb_session(
            project["id"],
            opened_offset_minutes=300,
            closed_offset_minutes=240,
        )
        middle = insert_dwb_session(
            project["id"],
            opened_offset_minutes=200,
            closed_offset_minutes=120,
        )
        newest = insert_dwb_session(
            project["id"], opened_offset_minutes=60
        )

        r = client.get(f"/api/projects/{project['id']}/sessions")
        assert r.status_code == 200
        body = r.json()
        ids = [row["id"] for row in body]
        assert ids == [newest.id, middle.id, oldest.id]

    def test_status_open_vs_closed(
        self, client, make_project, insert_dwb_session
    ):
        project = make_project()
        insert_dwb_session(
            project["id"],
            opened_offset_minutes=120,
            closed_offset_minutes=10,
        )
        insert_dwb_session(project["id"], opened_offset_minutes=30)

        r = client.get(f"/api/projects/{project['id']}/sessions")
        statuses = {row["status"] for row in r.json()}
        assert statuses == {"open", "closed"}

    def test_limit_and_offset(
        self, client, make_project, insert_dwb_session
    ):
        project = make_project()
        for i in range(5):
            insert_dwb_session(
                project["id"],
                opened_offset_minutes=100 - 10 * i,
                closed_offset_minutes=50 - 10 * i,
            )

        r = client.get(
            f"/api/projects/{project['id']}/sessions?limit=2&offset=2"
        )
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_unknown_project_returns_404(self, client):
        r = client.get("/api/projects/99999/sessions")
        assert r.status_code == 404

    def test_empty_project_returns_empty_list(self, client, make_project):
        project = make_project()
        r = client.get(f"/api/projects/{project['id']}/sessions")
        assert r.status_code == 200
        assert r.json() == []

    def test_cross_project_sessions_not_returned(
        self, client, make_project, insert_dwb_session
    ):
        a = make_project()
        b = make_project()
        insert_dwb_session(a["id"], opened_offset_minutes=60)
        b_session = insert_dwb_session(b["id"], opened_offset_minutes=60)

        r = client.get(f"/api/projects/{b['id']}/sessions")
        ids = [row["id"] for row in r.json()]
        assert ids == [b_session.id]


# ---------------------------------------------------------------------------
# GET /api/sessions/{id}
# ---------------------------------------------------------------------------


class TestSessionDetailMeta:
    def test_returns_meta_fields(
        self, client, make_project, insert_dwb_session
    ):
        project = make_project()
        sess = insert_dwb_session(
            project["id"],
            opened_offset_minutes=120,
            closed_offset_minutes=10,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
            open_phrase="you are archie, read the playbook",
            close_phrase="have the team write docs and exit",
            total_tokens=98765,
            total_time_seconds=6600,
        )

        r = client.get(f"/api/sessions/{sess.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == sess.id
        assert body["project_id"] == project["id"]
        assert body["open_method"] == "regex"
        assert body["close_method"] == "regex"
        assert body["close_reason"] == "explicit"
        assert body["open_phrase"] == "you are archie, read the playbook"
        assert body["close_phrase"] == "have the team write docs and exit"
        assert body["status"] == "closed"
        assert body["live"] is False
        assert body["total_tokens"] == 98765
        assert body["total_time_seconds"] == 6600

    def test_unknown_session_returns_404(self, client):
        r = client.get("/api/sessions/99999")
        assert r.status_code == 404


class TestSessionDetailLive:
    """Open sessions return live partials, not the stored (zero) totals."""

    def test_open_session_returns_live_flag_and_live_totals(
        self,
        client,
        make_project,
        make_agent,
        insert_dwb_session,
        insert_hook_session,
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"], role="backend-worker")
        sess = insert_dwb_session(project["id"], opened_offset_minutes=45)
        insert_hook_session(
            project["id"],
            session_id="live-1",
            agent_id=agent["id"],
            start_offset_minutes=40,
            end_offset_minutes=30,
            total_tokens=12000,
            dwb_session_id=sess.id,
        )

        r = client.get(f"/api/sessions/{sess.id}")
        body = r.json()
        assert body["status"] == "open"
        assert body["live"] is True
        # Live tokens come from linked hook_session rollup, not the stored
        # (still-zero) totals.
        assert body["total_tokens"] == 12000
        # Wall clock since opened_at — give 10s slack for test latency.
        assert body["total_time_seconds"] >= 45 * 60 - 10


class TestSessionDetailByRole:
    def test_groups_hook_sessions_by_agent_role(
        self,
        client,
        make_project,
        make_agent,
        insert_dwb_session,
        insert_hook_session,
    ):
        project = make_project()
        tl = make_agent(project_id=project["id"], role="team-lead")
        worker = make_agent(project_id=project["id"], role="backend-worker")
        sess = insert_dwb_session(
            project["id"],
            opened_offset_minutes=120,
            closed_offset_minutes=10,
            total_tokens=20000,
            total_time_seconds=6600,
        )
        # TL ran 2 hook_sessions; worker ran 1.
        insert_hook_session(
            project["id"],
            session_id="tl-1",
            agent_id=tl["id"],
            start_offset_minutes=100,
            end_offset_minutes=60,
            total_tokens=5000,
            dwb_session_id=sess.id,
        )
        insert_hook_session(
            project["id"],
            session_id="tl-2",
            agent_id=tl["id"],
            start_offset_minutes=50,
            end_offset_minutes=20,
            total_tokens=3000,
            dwb_session_id=sess.id,
        )
        insert_hook_session(
            project["id"],
            session_id="worker-1",
            agent_id=worker["id"],
            start_offset_minutes=80,
            end_offset_minutes=40,
            total_tokens=7000,
            dwb_session_id=sess.id,
        )

        r = client.get(f"/api/sessions/{sess.id}")
        body = r.json()
        by_role = {row["agent_id"]: row for row in body["by_role"]}
        assert by_role[tl["id"]]["tokens"] == 8000
        assert by_role[tl["id"]]["role"] == "team-lead"
        assert by_role[worker["id"]]["tokens"] == 7000
        assert by_role[worker["id"]]["role"] == "backend-worker"
        # Time is positive for both.
        assert by_role[tl["id"]]["time_seconds"] > 0
        assert by_role[worker["id"]]["time_seconds"] > 0

    def test_cross_project_agents_filtered_out(
        self,
        client,
        make_project,
        make_agent,
        insert_dwb_session,
        insert_hook_session,
    ):
        a = make_project()
        b = make_project()
        a_agent = make_agent(project_id=a["id"], role="team-lead")
        b_agent = make_agent(project_id=b["id"], role="backend-worker")
        sess_a = insert_dwb_session(
            a["id"], opened_offset_minutes=60, closed_offset_minutes=10
        )
        insert_hook_session(
            a["id"],
            session_id="a-hook",
            agent_id=a_agent["id"],
            start_offset_minutes=50,
            end_offset_minutes=20,
            total_tokens=4000,
            dwb_session_id=sess_a.id,
        )
        # Cross-project hook_session in the same wall-clock window — must
        # NOT appear in session A's by_role.
        insert_hook_session(
            b["id"],
            session_id="b-hook-other-project",
            agent_id=b_agent["id"],
            start_offset_minutes=50,
            end_offset_minutes=20,
            total_tokens=99999,
        )

        r = client.get(f"/api/sessions/{sess_a.id}")
        body = r.json()
        agent_ids = {row["agent_id"] for row in body["by_role"]}
        assert agent_ids == {a_agent["id"]}


class TestSessionDetailByTicket:
    def test_groups_tracking_log_by_ticket_within_window(
        self,
        client,
        make_project,
        make_agent,
        make_ticket,
        insert_dwb_session,
        insert_tracking,
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"], role="backend-worker")
        ticket_in = make_ticket(project_id=project["id"])
        ticket_out = make_ticket(project_id=project["id"])
        sess = insert_dwb_session(
            project["id"],
            opened_offset_minutes=120,
            closed_offset_minutes=10,
        )

        # Inside window: token_report on ticket_in.
        insert_tracking(
            project_id=project["id"],
            agent_id=agent["id"],
            ticket_id=ticket_in["id"],
            event_type="token_report",
            offset_minutes=60,
            tokens=4200,
        )
        # Inside window: start/stop pair on ticket_in (30 minutes apart).
        insert_tracking(
            project_id=project["id"],
            agent_id=agent["id"],
            ticket_id=ticket_in["id"],
            event_type="start",
            offset_minutes=90,
        )
        insert_tracking(
            project_id=project["id"],
            agent_id=agent["id"],
            ticket_id=ticket_in["id"],
            event_type="stop",
            offset_minutes=60,
        )
        # Outside window: token_report on ticket_out at 5min ago (after close).
        insert_tracking(
            project_id=project["id"],
            agent_id=agent["id"],
            ticket_id=ticket_out["id"],
            event_type="token_report",
            offset_minutes=5,
            tokens=9999,
        )

        r = client.get(f"/api/sessions/{sess.id}")
        body = r.json()
        by_ticket = {row["ticket_id"]: row for row in body["by_ticket"]}
        assert ticket_in["id"] in by_ticket
        assert ticket_out["id"] not in by_ticket  # outside window
        assert by_ticket[ticket_in["id"]]["tokens"] == 4200
        # 30 minutes between start and stop, fully inside window.
        assert by_ticket[ticket_in["id"]]["time_seconds"] == 30 * 60
        assert by_ticket[ticket_in["id"]]["ticket_key"] == ticket_in["ticket_key"]


class TestSessionDetailOverhead:
    def test_overhead_split_between_tl_and_pm(
        self,
        client,
        make_project,
        make_agent,
        insert_dwb_session,
        insert_tracking,
    ):
        project = make_project()
        tl = make_agent(project_id=project["id"], role="team-lead")
        pm = make_agent(project_id=project["id"], role="pm")
        worker = make_agent(project_id=project["id"], role="backend-worker")
        sess = insert_dwb_session(
            project["id"],
            opened_offset_minutes=120,
            closed_offset_minutes=10,
        )

        # In-window overhead — TL 1500, PM 800, worker 300 (worker rolls
        # into TL bucket per DWB-305 invariant).
        insert_tracking(
            project_id=project["id"],
            agent_id=tl["id"],
            event_type="overhead_token_report",
            offset_minutes=60,
            tokens=1500,
        )
        insert_tracking(
            project_id=project["id"],
            agent_id=pm["id"],
            event_type="overhead_token_report",
            offset_minutes=40,
            tokens=800,
        )
        insert_tracking(
            project_id=project["id"],
            agent_id=worker["id"],
            event_type="overhead_token_report",
            offset_minutes=20,
            tokens=300,
        )
        # Out of window (before opened_at): must NOT count.
        insert_tracking(
            project_id=project["id"],
            agent_id=tl["id"],
            event_type="overhead_token_report",
            offset_minutes=240,
            tokens=999999,
        )

        r = client.get(f"/api/sessions/{sess.id}")
        body = r.json()
        assert body["tl_overhead_tokens"] == 1500 + 300
        assert body["pm_overhead_tokens"] == 800
