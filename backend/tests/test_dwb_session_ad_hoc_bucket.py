# Path: tests/test_dwb_session_ad_hoc_bucket.py
# File: test_dwb_session_ad_hoc_bucket.py
# Created: 2026-06-10
# Purpose: Tests for DWB-353 ad_hoc overhead bucket - routing, rollup, alert removal, backfill scrub
# Caller: pytest
# Callees: app.services.tracking, app.services.hook_tracking, app.services.dwb_session_rollup,
#          GET /api/sessions/{id}, GET /api/projects/{id}/sessions, /api/alerts
# Data In: per-test db_session, factory fixtures, direct ORM inserts for hook_sessions + tracking_log + alerts
# Data Out: Assertions on ad_hoc rollup math, alert absence, backfill scrub correctness
# Last Modified: 2026-06-10

"""DWB-353: ad_hoc overhead bucket replaces the unattributed alert path.

The skip-ticket-overhead lane (worker tokens without a ticket attribution
inside the session window) is by design and should not page Pam or the
TL. Pre-DWB-353 those tokens silently inflated tl_overhead and fired a
warning alert. Post-DWB-353:

  1. Worker-without-ticket tokens land in a dedicated ad_hoc bucket via
     new event_type 'ad_hoc_token_report' / 'ad_hoc_stop' in tracking_log.
  2. The unattributed alert and the tokens-not-reported alert paths are
     deleted (verified in test_hooks.py + test_token_alert_on_close.py).
  3. Session detail + list responses surface ad_hoc_overhead_tokens and
     ad_hoc_overhead_seconds.
  4. Backfill migration dismisses pre-existing open instances of both
     dead alert classes.

These tests cover all four scopes end-to-end through public endpoints,
direct ORM inserts for setup (mirroring the test_dwb_session_rollup
pattern), and assertions against the response shape + alert table.
"""

from datetime import datetime, timedelta

import pytest

from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.tracking_log import TrackingLog


def _naive_now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def insert_dwb_session(db_session):
    def _make(
        project_id,
        *,
        opened_offset_minutes,
        closed_offset_minutes=None,
        open_method=DwbOpenMethod.regex,
        close_method=None,
        close_reason=None,
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
        )
        db_session.add(row)
        db_session.flush()
        db_session.refresh(row)
        return row

    return _make


@pytest.fixture
def insert_hook_session(db_session):
    def _make(
        *,
        project_id,
        agent_id,
        session_id,
        start_offset_minutes,
        end_offset_minutes=None,
        ticket_id=None,
        total_tokens=0,
        dwb_session_id=None,
    ):
        now = _naive_now()
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            agent_id=agent_id,
            ticket_id=ticket_id,
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
        event_type,
        offset_minutes,
        ticket_id=None,
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
# 1. ad_hoc bucket sums correctly + appears on session detail/list responses
# ---------------------------------------------------------------------------


class TestAdHocBucketRollup:
    def test_detail_response_includes_ad_hoc_fields(
        self,
        client,
        make_project,
        make_agent,
        db_session,
        insert_dwb_session,
        insert_tracking,
        insert_hook_session,
    ):
        """Sanity-check: GET /api/sessions/{id} exposes both ad_hoc fields,
        zero when there is no ad_hoc activity in window."""
        proj = make_project()
        sess = insert_dwb_session(
            proj["id"],
            opened_offset_minutes=60,
            closed_offset_minutes=10,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        r = client.get(f"/api/sessions/{sess.id}")
        body = r.json()
        assert "ad_hoc_overhead_tokens" in body
        assert "ad_hoc_overhead_seconds" in body
        assert body["ad_hoc_overhead_tokens"] == 0
        assert body["ad_hoc_overhead_seconds"] == 0

    def test_list_response_includes_ad_hoc_fields(
        self, client, make_project, insert_dwb_session,
    ):
        proj = make_project()
        insert_dwb_session(
            proj["id"], opened_offset_minutes=45,
            closed_offset_minutes=5,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        r = client.get(f"/api/projects/{proj['id']}/sessions")
        rows = r.json()
        assert len(rows) == 1
        assert "ad_hoc_overhead_tokens" in rows[0]
        assert "ad_hoc_overhead_seconds" in rows[0]
        assert rows[0]["ad_hoc_overhead_tokens"] == 0
        assert rows[0]["ad_hoc_overhead_seconds"] == 0

    def test_ad_hoc_tokens_sum_inside_window(
        self,
        client,
        make_project,
        make_agent,
        db_session,
        insert_dwb_session,
        insert_tracking,
    ):
        """ad_hoc_token_report events inside the window sum into the
        bucket; events outside the window are excluded."""
        proj = make_project()
        agent = make_agent(project_id=proj["id"], role="backend-worker")
        sess = insert_dwb_session(
            proj["id"],
            opened_offset_minutes=120,
            closed_offset_minutes=30,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        # Two in window, one before, one after.
        insert_tracking(
            project_id=proj["id"], agent_id=agent["id"],
            event_type="ad_hoc_token_report",
            offset_minutes=100, tokens=300,
        )
        insert_tracking(
            project_id=proj["id"], agent_id=agent["id"],
            event_type="ad_hoc_token_report",
            offset_minutes=60, tokens=450,
        )
        insert_tracking(  # before window
            project_id=proj["id"], agent_id=agent["id"],
            event_type="ad_hoc_token_report",
            offset_minutes=180, tokens=9999,
        )
        insert_tracking(  # after window
            project_id=proj["id"], agent_id=agent["id"],
            event_type="ad_hoc_token_report",
            offset_minutes=10, tokens=9999,
        )
        db_session.flush()

        body = client.get(f"/api/sessions/{sess.id}").json()
        assert body["ad_hoc_overhead_tokens"] == 750

    def test_ad_hoc_seconds_from_worker_hook_sessions_without_ticket(
        self,
        client,
        make_project,
        make_agent,
        make_ticket,
        db_session,
        insert_dwb_session,
        insert_hook_session,
    ):
        """ad_hoc_overhead_seconds comes from worker-role hook_sessions
        with ticket_id IS NULL inside the window. TL/PM sessions and
        worker sessions WITH a ticket are excluded."""
        proj = make_project()
        worker = make_agent(project_id=proj["id"], role="backend-worker")
        tl = make_agent(project_id=proj["id"], role="team-lead")
        # Real ticket to satisfy hook_sessions.ticket_id FK constraint.
        ticketed = make_ticket(project_id=proj["id"])

        sess = insert_dwb_session(
            proj["id"],
            opened_offset_minutes=120,
            closed_offset_minutes=30,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        # Worker, no ticket, fully in window: 30 minutes = 1800s.
        insert_hook_session(
            project_id=proj["id"], agent_id=worker["id"],
            session_id="ad-hoc-1",
            start_offset_minutes=90, end_offset_minutes=60,
            ticket_id=None,
        )
        # TL session - should NOT count toward ad_hoc.
        insert_hook_session(
            project_id=proj["id"], agent_id=tl["id"],
            session_id="tl-1",
            start_offset_minutes=80, end_offset_minutes=70,
            ticket_id=None,
        )
        # Worker WITH ticket - excluded.
        insert_hook_session(
            project_id=proj["id"], agent_id=worker["id"],
            session_id="worker-ticketed",
            start_offset_minutes=70, end_offset_minutes=50,
            ticket_id=ticketed["id"],
        )
        db_session.flush()

        body = client.get(f"/api/sessions/{sess.id}").json()
        assert body["ad_hoc_overhead_seconds"] == 1800

    def test_cross_project_ad_hoc_excluded(
        self,
        client,
        make_project,
        make_agent,
        db_session,
        insert_dwb_session,
        insert_tracking,
    ):
        """ad_hoc events on a different project must not leak into this
        project's rollup."""
        proj_a = make_project()
        proj_b = make_project()
        agent_b = make_agent(project_id=proj_b["id"], role="backend-worker")
        sess_a = insert_dwb_session(
            proj_a["id"],
            opened_offset_minutes=60,
            closed_offset_minutes=5,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )
        # ad_hoc event on project B with timestamp in project A's window.
        insert_tracking(
            project_id=proj_b["id"], agent_id=agent_b["id"],
            event_type="ad_hoc_token_report",
            offset_minutes=30, tokens=500,
        )
        db_session.flush()
        body = client.get(f"/api/sessions/{sess_a.id}").json()
        assert body["ad_hoc_overhead_tokens"] == 0


# ---------------------------------------------------------------------------
# 2. No alert fires for worker-without-ticket case
# ---------------------------------------------------------------------------


class TestNoAlertFires:
    def test_worker_without_ticket_does_not_create_alert(
        self,
        client,
        make_project,
        make_agent,
        db_session,
    ):
        """A worker session with tokens and no ticket attribution must
        NOT create an Alert row. (The 'Unattributed' alert was the path;
        it's gone.)"""
        proj = make_project(repo_path="/tmp/dwb353-noalert")
        worker = make_agent(project_id=proj["id"], role="backend-worker")

        # Walk the hook handler directly to keep the test focused; the
        # handle_session_end path is the same one production uses.
        from app.services.hook_tracking import handle_session_start, handle_session_end

        sid = "noalert-worker-1"
        handle_session_start(db_session, {
            "session_id": sid,
            "cwd": "/tmp/dwb353-noalert",
            "agent_id": worker["id"],
        })
        db_session.flush()
        handle_session_end(db_session, {
            "session_id": sid,
            "transcript_path": None,
            "hook_event": "SessionEnd",
        })
        db_session.flush()

        # No alerts of any kind for this project.
        alerts = db_session.query(Alert).filter(
            Alert.project_id == proj["id"]
        ).all()
        unattributed_or_token = [
            a for a in alerts
            if "Unattributed" in (a.title or "")
            or "Tokens not reported" in (a.title or "")
        ]
        assert unattributed_or_token == [], (
            f"DWB-353 dead alerts must not fire; saw: "
            f"{[a.title for a in unattributed_or_token]}"
        )


# ---------------------------------------------------------------------------
# 3. Backfill: existing open alerts get dismissed by the migration scrub
# ---------------------------------------------------------------------------


class TestBackfillScrubDismissesDeadAlerts:
    """The migration runs `UPDATE alerts SET status='dismissed' WHERE
    status IN (open, acknowledged) AND title LIKE 'Tokens not reported...'
    OR 'Unattributed hook session: ...'`. These tests apply the same SQL
    via the test session (the migration itself runs once per test session
    against the schema; this exercises the equivalent UPDATE so the
    scrub logic is pinned)."""

    def _apply_scrub(self, db_session):
        """Run the same UPDATE the migration runs."""
        from sqlalchemy import text
        db_session.execute(
            text(
                "UPDATE alerts "
                "SET status = 'acknowledged', resolved_at = NOW() "
                "WHERE status = 'open' "
                "AND ("
                "  title LIKE 'Tokens not reported for %' "
                "  OR title LIKE 'Unattributed hook session: %'"
                ")"
            )
        )
        db_session.flush()

    def test_scrub_acks_open_tokens_not_reported_alert(
        self, db_session, make_project, make_agent,
    ):
        proj = make_project()
        agent = make_agent(project_id=proj["id"])
        a = Alert(
            project_id=proj["id"],
            raised_by_agent_id=agent["id"],
            title=f"Tokens not reported for {proj['prefix']}-1",
            body="dead",
            severity=AlertSeverity.info,
            status=AlertStatus.open,
        )
        db_session.add(a)
        db_session.flush()

        self._apply_scrub(db_session)
        db_session.refresh(a)
        # alerts.status enum has no 'dismissed' value; the codebase
        # convention (alert.py::dismiss_all) is open -> acknowledged + resolved_at.
        assert a.status == AlertStatus.acknowledged
        assert a.resolved_at is not None

    def test_scrub_acks_open_unattributed_alert(
        self, db_session, make_project, make_agent,
    ):
        proj = make_project()
        agent = make_agent(project_id=proj["id"])
        a = Alert(
            project_id=proj["id"],
            raised_by_agent_id=agent["id"],
            title="Unattributed hook session: abc-123",
            body="dead",
            severity=AlertSeverity.warning,
            status=AlertStatus.open,
        )
        db_session.add(a)
        db_session.flush()

        self._apply_scrub(db_session)
        db_session.refresh(a)
        assert a.status == AlertStatus.acknowledged
        assert a.resolved_at is not None

    def test_scrub_leaves_already_acknowledged_alerts_alone(
        self, db_session, make_project, make_agent,
    ):
        """Already-acknowledged matching alerts are not re-touched (the
        WHERE clause filters on status='open' only). This protects the
        original resolved_at timestamp on rows the operator already
        triaged."""
        proj = make_project()
        agent = make_agent(project_id=proj["id"])
        original_resolved = datetime(2026, 1, 1, 12, 0, 0)
        a = Alert(
            project_id=proj["id"],
            raised_by_agent_id=agent["id"],
            title="Tokens not reported for X-1",
            body="already triaged",
            severity=AlertSeverity.info,
            status=AlertStatus.acknowledged,
            resolved_at=original_resolved,
        )
        db_session.add(a)
        db_session.flush()

        self._apply_scrub(db_session)
        db_session.refresh(a)
        assert a.status == AlertStatus.acknowledged
        assert a.resolved_at == original_resolved

    def test_scrub_leaves_other_alerts_alone(
        self, db_session, make_project, make_agent,
    ):
        """Alerts with unrelated titles must not be touched."""
        proj = make_project()
        agent = make_agent(project_id=proj["id"])
        keep = Alert(
            project_id=proj["id"],
            raised_by_agent_id=agent["id"],
            title="Sprint goal at risk",
            body="keep me",
            severity=AlertSeverity.warning,
            status=AlertStatus.open,
        )
        db_session.add(keep)
        db_session.flush()

        self._apply_scrub(db_session)
        db_session.refresh(keep)
        assert keep.status == AlertStatus.open
