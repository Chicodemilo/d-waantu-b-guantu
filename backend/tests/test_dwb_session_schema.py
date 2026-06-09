# Path: tests/test_dwb_session_schema.py
# File: test_dwb_session_schema.py
# Created: 2026-06-09
# Purpose: Schema-level tests for DwbSession (DWB-335) — single-active constraint, FK on hook_sessions, model round-trip
# Caller: pytest
# Callees: app.models.dwb_session, app.schemas.dwb_session, app.models.hook_session
# Data In: per-test db_session, factory fixtures
# Data Out: Assertions on IntegrityError, FK behavior, schema serialization
# Last Modified: 2026-06-09

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.schemas.dwb_session import DwbSessionRead


def _utc_now_naive():
    """The DB stores naive DATETIME with 1-second resolution; drop tzinfo +
    microseconds so equality holds after round-trip through MySQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class TestSingleActiveConstraint:
    """The (project_id, is_open) UNIQUE index enforces at most one row per
    project with closed_at IS NULL. Closed rows (is_open=NULL) never collide."""

    def test_first_open_session_persists(self, db_session, make_project):
        project = make_project()
        row = DwbSession(
            project_id=project["id"],
            opened_at=_utc_now_naive(),
            open_method=DwbOpenMethod.regex,
        )
        db_session.add(row)
        db_session.flush()
        assert row.id is not None
        # generated column populated by the server
        db_session.refresh(row)
        assert row.is_open == 1

    def test_second_open_for_same_project_refused(self, db_session, make_project):
        project = make_project()
        first = DwbSession(
            project_id=project["id"],
            opened_at=_utc_now_naive(),
            open_method=DwbOpenMethod.regex,
        )
        db_session.add(first)
        db_session.flush()

        second = DwbSession(
            project_id=project["id"],
            opened_at=_utc_now_naive(),
            open_method=DwbOpenMethod.ai_confident,
        )
        db_session.add(second)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_open_session_in_different_project_is_fine(
        self, db_session, make_project
    ):
        p1 = make_project()
        p2 = make_project()
        a = DwbSession(
            project_id=p1["id"],
            opened_at=_utc_now_naive(),
            open_method=DwbOpenMethod.regex,
        )
        b = DwbSession(
            project_id=p2["id"],
            opened_at=_utc_now_naive(),
            open_method=DwbOpenMethod.regex,
        )
        db_session.add_all([a, b])
        db_session.flush()
        assert a.id and b.id and a.id != b.id

    def test_reopen_after_close_is_fine(self, db_session, make_project):
        project = make_project()
        first = DwbSession(
            project_id=project["id"],
            opened_at=_utc_now_naive() - timedelta(hours=1),
            open_method=DwbOpenMethod.regex,
        )
        db_session.add(first)
        db_session.flush()

        # Close it.
        first.closed_at = _utc_now_naive()
        first.close_method = DwbCloseMethod.regex
        first.close_reason = DwbCloseReason.explicit
        db_session.flush()
        db_session.refresh(first)
        assert first.is_open is None  # generated column flips to NULL

        # Now a new open for the same project must succeed.
        second = DwbSession(
            project_id=project["id"],
            opened_at=_utc_now_naive(),
            open_method=DwbOpenMethod.ai_confident,
        )
        db_session.add(second)
        db_session.flush()
        assert second.id is not None and second.id != first.id

    def test_many_closed_sessions_per_project_allowed(
        self, db_session, make_project
    ):
        project = make_project()
        for i in range(5):
            row = DwbSession(
                project_id=project["id"],
                opened_at=_utc_now_naive() - timedelta(hours=i + 1),
                closed_at=_utc_now_naive() - timedelta(hours=i),
                open_method=DwbOpenMethod.regex,
                close_method=DwbCloseMethod.regex,
                close_reason=DwbCloseReason.explicit,
            )
            db_session.add(row)
        db_session.flush()


class TestHookSessionFK:
    """hook_sessions.dwb_session_id is nullable and references dwb_sessions.id.
    Historical rows (created before DWB sessions existed) must remain valid
    with NULL."""

    def test_hook_session_with_null_dwb_session_id_is_valid(
        self, db_session, make_project
    ):
        project = make_project()
        hs = HookSession(
            session_id="test-null-dwb-link",
            project_id=project["id"],
            start_time=_utc_now_naive(),
            status=HookSessionStatus.active,
            session_type=HookSessionType.teammate,
            total_tokens=0,
            dwb_session_id=None,
        )
        db_session.add(hs)
        db_session.flush()
        assert hs.id is not None
        assert hs.dwb_session_id is None

    def test_hook_session_can_link_to_dwb_session(
        self, db_session, make_project
    ):
        project = make_project()
        dwb = DwbSession(
            project_id=project["id"],
            opened_at=_utc_now_naive(),
            open_method=DwbOpenMethod.regex,
        )
        db_session.add(dwb)
        db_session.flush()

        hs = HookSession(
            session_id="test-linked-dwb",
            project_id=project["id"],
            start_time=_utc_now_naive(),
            status=HookSessionStatus.active,
            session_type=HookSessionType.teammate,
            total_tokens=0,
            dwb_session_id=dwb.id,
        )
        db_session.add(hs)
        db_session.flush()
        assert hs.dwb_session_id == dwb.id

    def test_hook_session_fk_rejects_invalid_dwb_session(
        self, db_session, make_project
    ):
        project = make_project()
        hs = HookSession(
            session_id="test-bad-fk",
            project_id=project["id"],
            start_time=_utc_now_naive(),
            status=HookSessionStatus.active,
            session_type=HookSessionType.teammate,
            total_tokens=0,
            dwb_session_id=999_999_999,  # does not exist
        )
        db_session.add(hs)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


class TestModelSchemaRoundTrip:
    """DwbSession ORM -> DwbSessionRead Pydantic round-trip covers serialization
    of all enum fields and the generated is_open marker."""

    def test_round_trip_open_session(self, db_session, make_project):
        project = make_project()
        opened = _utc_now_naive()
        row = DwbSession(
            project_id=project["id"],
            opened_at=opened,
            open_method=DwbOpenMethod.ai_asked,
            open_phrase="you are archie, read the playbook",
        )
        db_session.add(row)
        db_session.flush()
        db_session.refresh(row)

        read = DwbSessionRead.model_validate(row)
        assert read.id == row.id
        assert read.project_id == project["id"]
        assert read.opened_at == opened
        assert read.closed_at is None
        assert read.open_method == DwbOpenMethod.ai_asked
        assert read.open_phrase == "you are archie, read the playbook"
        assert read.close_method is None
        assert read.close_reason is None
        assert read.total_tokens == 0
        assert read.total_time_seconds == 0
        assert read.is_open == 1

    def test_round_trip_closed_session(self, db_session, make_project):
        project = make_project()
        opened = _utc_now_naive() - timedelta(hours=2)
        closed = _utc_now_naive()
        row = DwbSession(
            project_id=project["id"],
            opened_at=opened,
            closed_at=closed,
            open_method=DwbOpenMethod.regex,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
            total_tokens=12345,
            total_time_seconds=7200,
        )
        db_session.add(row)
        db_session.flush()
        db_session.refresh(row)

        read = DwbSessionRead.model_validate(row)
        assert read.closed_at == closed
        assert read.close_method == DwbCloseMethod.idle_timeout
        assert read.close_reason == DwbCloseReason.idle
        assert read.total_tokens == 12345
        assert read.total_time_seconds == 7200
        assert read.is_open is None
