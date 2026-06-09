# Path: tests/test_idle_sweeper.py
# File: test_idle_sweeper.py
# Created: 2026-06-09
# Purpose: Tests for the DWB session idle-timeout sweeper service (DWB-337)
# Caller: pytest
# Callees: app.services.dwb_session, app.services.idle_sweeper
# Data In: per-test db_session, factory fixtures, hand-rolled DwbSession + HookSession rows
# Data Out: Assertions on closed_at, close_method, close_reason, rollup fields
# Last Modified: 2026-06-09

"""Coverage for:
- 65min-idle DWB session gets auto-closed with close_method=idle_timeout
- 30min-idle DWB session stays open
- Recent worker activity (hook_session.end_time) keeps a session alive
- Recent tracking_log entry keeps a session alive
- Already-closed sessions are ignored (no double-close)
- close_session idempotency
- total_tokens rollup from linked hook_sessions only
- total_time_seconds matches wall clock open -> close

These exercise the service layer directly (sweep_idle_sessions / close_session)
so they don't depend on the asyncio task loop, which is disabled in tests
via the TESTING env var.
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
from app.services.dwb_session import (
    close_session,
    compute_last_activity,
    find_idle_sessions,
    sweep_idle_sessions,
)


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def insert_open_dwb_session(db_session):
    """Insert an open DwbSession via the per-test session so it shares the
    test's transaction (mirrors test_hook_orphan_sessions pattern)."""

    def _make(project_id, *, opened_offset_minutes=0):
        row = DwbSession(
            project_id=project_id,
            opened_at=_naive_now() - timedelta(minutes=opened_offset_minutes),
            open_method=DwbOpenMethod.regex,
            open_phrase="you are archie, read the playbook",
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture
def insert_hook_session(db_session):
    def _make(
        project_id,
        *,
        session_id,
        end_offset_minutes=None,
        start_offset_minutes=0,
        total_tokens=0,
        dwb_session_id=None,
        status=HookSessionStatus.completed,
    ):
        now = _naive_now()
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            start_time=now - timedelta(minutes=start_offset_minutes),
            end_time=(
                None
                if end_offset_minutes is None
                else now - timedelta(minutes=end_offset_minutes)
            ),
            status=status,
            session_type=HookSessionType.teammate,
            total_tokens=total_tokens,
            dwb_session_id=dwb_session_id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture
def insert_tracking_log(db_session, make_agent):
    def _make(project_id, *, offset_minutes=0, agent_id=None):
        if agent_id is None:
            agent = make_agent(project_id=project_id)
            agent_id = agent["id"]
        row = TrackingLog(
            project_id=project_id,
            agent_id=agent_id,
            event_type="token_report",
            tokens=0,
            timestamp=_naive_now() - timedelta(minutes=offset_minutes),
            source="test",
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


class TestSweepClosesIdle:
    def test_session_idle_65min_gets_closed(
        self, db_session, make_project, insert_open_dwb_session
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=65
        )

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.flush()
        db_session.refresh(session)

        assert closed_count == 1
        assert session.closed_at is not None
        assert session.close_method == DwbCloseMethod.idle_timeout
        assert session.close_reason == DwbCloseReason.idle
        assert session.close_phrase is None
        # is_open is the generated column — must flip to NULL on close.
        assert session.is_open is None

    def test_session_idle_30min_stays_open(
        self, db_session, make_project, insert_open_dwb_session
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=30
        )

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.flush()
        db_session.refresh(session)

        assert closed_count == 0
        assert session.closed_at is None
        assert session.is_open == 1


class TestActivityKeepsAlive:
    def test_recent_hook_session_keeps_dwb_session_alive(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_hook_session,
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=90
        )
        # Hook session that ended 10 min ago — recent activity.
        insert_hook_session(
            project["id"],
            session_id="recent-completed",
            end_offset_minutes=10,
            start_offset_minutes=20,
            total_tokens=1234,
            dwb_session_id=session.id,
        )

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.refresh(session)

        assert closed_count == 0
        assert session.closed_at is None

    def test_active_worker_hook_session_keeps_dwb_alive(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_hook_session,
    ):
        """A hook_session that started recently but hasn't ended yet (end_time
        IS NULL) is an active worker — must count as activity, not be ignored
        for lacking an end_time."""
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=120
        )
        insert_hook_session(
            project["id"],
            session_id="worker-still-running",
            start_offset_minutes=15,
            end_offset_minutes=None,  # still open
            status=HookSessionStatus.active,
            dwb_session_id=session.id,
        )

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.refresh(session)

        assert closed_count == 0
        assert session.closed_at is None

    def test_recent_tracking_log_keeps_session_alive(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_tracking_log,
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=90
        )
        insert_tracking_log(project["id"], offset_minutes=5)

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.refresh(session)

        assert closed_count == 0
        assert session.closed_at is None

    def test_stale_hook_session_does_not_keep_alive(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_hook_session,
    ):
        """A hook_session that ended 90min ago is OLDER than the idle window,
        so the parent DWB session should still close."""
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=120
        )
        insert_hook_session(
            project["id"],
            session_id="long-stale",
            start_offset_minutes=100,
            end_offset_minutes=90,
            dwb_session_id=session.id,
        )

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.refresh(session)

        assert closed_count == 1
        assert session.closed_at is not None


class TestAlreadyClosed:
    def test_already_closed_session_is_ignored(
        self, db_session, make_project
    ):
        project = make_project()
        row = DwbSession(
            project_id=project["id"],
            opened_at=_naive_now() - timedelta(hours=3),
            closed_at=_naive_now() - timedelta(hours=1),
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        db_session.add(row)
        db_session.flush()
        original_closed_at = row.closed_at

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.refresh(row)

        assert closed_count == 0
        # Original close fields are preserved — sweep did not overwrite.
        assert row.closed_at == original_closed_at
        assert row.close_method == DwbCloseMethod.regex
        assert row.close_reason == DwbCloseReason.explicit


class TestCloseSession:
    def test_close_session_is_idempotent(
        self, db_session, make_project, insert_open_dwb_session
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=90
        )
        close_session(
            db_session,
            session,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        first_closed_at = session.closed_at

        # Second call must not move closed_at or change the close method.
        close_session(
            db_session,
            session,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        assert session.closed_at == first_closed_at
        assert session.close_method == DwbCloseMethod.idle_timeout
        assert session.close_reason == DwbCloseReason.idle

    def test_close_rolls_up_linked_hook_session_tokens(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_hook_session,
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=10
        )
        insert_hook_session(
            project["id"],
            session_id="linked-1",
            end_offset_minutes=8,
            start_offset_minutes=9,
            total_tokens=5000,
            dwb_session_id=session.id,
        )
        insert_hook_session(
            project["id"],
            session_id="linked-2",
            end_offset_minutes=3,
            start_offset_minutes=4,
            total_tokens=7500,
            dwb_session_id=session.id,
        )
        # Project-wide hook session NOT linked — must NOT be included in
        # the rollup (avoids double-counting prior DWB sessions on the
        # same project).
        insert_hook_session(
            project["id"],
            session_id="unlinked",
            end_offset_minutes=5,
            start_offset_minutes=6,
            total_tokens=99999,
            dwb_session_id=None,
        )

        close_session(
            db_session,
            session,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )
        db_session.refresh(session)

        assert session.total_tokens == 12500

    def test_close_sets_total_time_seconds_from_wall_clock(
        self, db_session, make_project
    ):
        project = make_project()
        opened = _naive_now() - timedelta(hours=2, minutes=30)
        session = DwbSession(
            project_id=project["id"],
            opened_at=opened,
            open_method=DwbOpenMethod.regex,
        )
        db_session.add(session)
        db_session.flush()

        fixed_now = opened + timedelta(hours=2, minutes=30)
        close_session(
            db_session,
            session,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
            now=fixed_now,
        )
        assert session.total_time_seconds == 2 * 3600 + 30 * 60


class TestComputeLastActivity:
    """Sanity checks on the activity computation itself — sweep_idle_sessions
    builds on this, so a bug here is hard to catch from sweep tests alone."""

    def test_returns_opened_at_when_no_activity(
        self, db_session, make_project, insert_open_dwb_session
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=10
        )
        ts = compute_last_activity(db_session, session)
        # Within a second of opened_at (tests truncate to whole seconds).
        assert abs((ts - session.opened_at).total_seconds()) < 2

    def test_returns_max_of_hook_and_tracking(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_hook_session,
        insert_tracking_log,
    ):
        project = make_project()
        session = insert_open_dwb_session(
            project["id"], opened_offset_minutes=120
        )
        # tracking_log 20 min ago
        insert_tracking_log(project["id"], offset_minutes=20)
        # hook_session ending 5 min ago — newer
        insert_hook_session(
            project["id"],
            session_id="newer",
            end_offset_minutes=5,
            start_offset_minutes=15,
            dwb_session_id=session.id,
        )
        ts = compute_last_activity(db_session, session)
        # max should be ~5 min ago, well within the last 10 min
        assert ts >= _naive_now() - timedelta(minutes=10)


class TestFindIdleSessions:
    def test_returns_only_open_sessions_past_threshold(
        self, db_session, make_project, insert_open_dwb_session
    ):
        p1 = make_project()
        p2 = make_project()
        p3 = make_project()
        old = insert_open_dwb_session(p1["id"], opened_offset_minutes=90)
        fresh = insert_open_dwb_session(p2["id"], opened_offset_minutes=10)
        # Already closed — must not be returned even though it's old.
        closed = DwbSession(
            project_id=p3["id"],
            opened_at=_naive_now() - timedelta(hours=5),
            closed_at=_naive_now() - timedelta(hours=2),
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        db_session.add(closed)
        db_session.flush()

        idle = find_idle_sessions(db_session, idle_minutes=60)
        ids = {s.id for s in idle}
        assert old.id in ids
        assert fresh.id not in ids
        assert closed.id not in ids
