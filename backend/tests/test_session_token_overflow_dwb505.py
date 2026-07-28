# Path: tests/test_session_token_overflow_dwb505.py
# File: test_session_token_overflow_dwb505.py
# Created: 2026-07-28
# Purpose: Regression tests for DWB-505 - BIGINT token columns, close-path clamp, and idle-sweeper per-session isolation
# Caller: pytest
# Callees: app.services.dwb_session (close_session, sweep_idle_sessions, _MAX_TOKEN_VALUE)
# Data In: per-test db_session, factory fixtures, hand-rolled DwbSession + HookSession rows
# Data Out: assertions on total_tokens persistence, clamping, and sweep isolation
# Last Modified: 2026-07-28

"""Coverage for DWB-505:

- A rollup that exceeds the old INT ceiling (2,147,483,647) now persists on
  close instead of raising MySQL 1264. This is the exact failure that 500'd
  every close of session 65 (5.47B-token rollup) before the columns were
  widened to BIGINT.
- A pathological rollup that would exceed even the BIGINT ceiling is clamped
  (not aborted) so the close can never 500.
- The idle sweeper isolates each close in its own SAVEPOINT: one session whose
  close raises no longer poisons the whole batch, so the other idle sessions
  still close (previously a single overflow rolled back the entire sweep and
  nothing closed cycle after cycle).
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
from app.services import dwb_session as dwb_session_svc
from app.services.dwb_session import (
    _MAX_TOKEN_VALUE,
    close_session,
    sweep_idle_sessions,
)

# Old signed-INT ceiling that used to hold total_tokens; the bug is that a
# rollup above this overflowed the column.
_OLD_INT_MAX = 2_147_483_647


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def insert_open_dwb_session(db_session):
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
    def _make(project_id, *, session_id, total_tokens, dwb_session_id):
        now = _naive_now()
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            start_time=now - timedelta(minutes=20),
            end_time=now - timedelta(minutes=10),
            status=HookSessionStatus.completed,
            session_type=HookSessionType.teammate,
            total_tokens=total_tokens,
            dwb_session_id=dwb_session_id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


class TestBigIntRollupPersists:
    def test_close_persists_rollup_above_old_int_ceiling(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_hook_session,
    ):
        """The real DWB-505 regression: a rollup > 2.147B must close cleanly.

        Before widening to BIGINT this raised pymysql 1264 (out of range) and
        the close 500'd. Two linked hook_sessions each above the old INT max
        sum to ~5.5B, mirroring session 65's live figure.
        """
        project = make_project()
        session = insert_open_dwb_session(project["id"], opened_offset_minutes=30)
        insert_hook_session(
            project["id"],
            session_id="dwb505-a",
            total_tokens=3_000_000_000,
            dwb_session_id=session.id,
        )
        insert_hook_session(
            project["id"],
            session_id="dwb505-b",
            total_tokens=2_479_293_087,
            dwb_session_id=session.id,
        )
        expected = 3_000_000_000 + 2_479_293_087
        assert expected > _OLD_INT_MAX  # would have overflowed the old column

        close_session(
            db_session,
            session,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
        )
        db_session.refresh(session)

        assert session.closed_at is not None
        assert session.total_tokens == expected


class TestClampPathologicalRollup:
    def test_close_clamps_rollup_above_bigint_ceiling(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        monkeypatch,
    ):
        """A rollup exceeding even the BIGINT ceiling is clamped, not aborted.

        Such a value can't be stored in a real hook_session (that column is
        BIGINT too), so the rollup is forced via monkeypatch to prove the
        close-path guard degrades gracefully instead of raising.
        """
        project = make_project()
        session = insert_open_dwb_session(project["id"], opened_offset_minutes=30)

        monkeypatch.setattr(
            dwb_session_svc,
            "_rollup_tokens",
            lambda db, s: _MAX_TOKEN_VALUE + 5000,
        )

        # Must NOT raise.
        close_session(
            db_session,
            session,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
        )
        db_session.refresh(session)

        assert session.closed_at is not None
        assert session.total_tokens == _MAX_TOKEN_VALUE

    def test_close_does_not_clamp_normal_rollup(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        insert_hook_session,
    ):
        """A normal rollup is persisted verbatim - the clamp only fires at the
        ceiling, it does not silently cap ordinary values."""
        project = make_project()
        session = insert_open_dwb_session(project["id"], opened_offset_minutes=30)
        insert_hook_session(
            project["id"],
            session_id="dwb505-normal",
            total_tokens=12_345,
            dwb_session_id=session.id,
        )

        close_session(
            db_session,
            session,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
        )
        db_session.refresh(session)

        assert session.total_tokens == 12_345


class TestSweepIsolation:
    def test_failing_session_does_not_poison_the_batch(
        self,
        db_session,
        make_project,
        insert_open_dwb_session,
        monkeypatch,
    ):
        """One session whose close raises must not stop the others closing.

        Before DWB-505 the whole sweep ran in one transaction: a single raising
        close propagated out and the caller rolled back everything, so NOTHING
        closed. Now each close runs in its own SAVEPOINT, so the good session
        still closes and the bad one is skipped.
        """
        p_bad = make_project()
        p_good = make_project()
        bad = insert_open_dwb_session(p_bad["id"], opened_offset_minutes=120)
        good = insert_open_dwb_session(p_good["id"], opened_offset_minutes=120)

        real_rollup = dwb_session_svc._rollup_tokens

        def _selective_rollup(db, s):
            if s.id == bad.id:
                raise RuntimeError("simulated per-session close failure")
            return real_rollup(db, s)

        monkeypatch.setattr(dwb_session_svc, "_rollup_tokens", _selective_rollup)

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)
        db_session.refresh(bad)
        db_session.refresh(good)

        assert closed_count == 1
        assert good.closed_at is not None
        assert good.close_method == DwbCloseMethod.idle_timeout
        # The failing session was rolled back to its savepoint and left open.
        assert bad.closed_at is None
        assert bad.is_open == 1
