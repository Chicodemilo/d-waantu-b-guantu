# Path: tests/test_backfill_session_synthesis.py
# File: test_backfill_session_synthesis.py
# Created: 2026-06-25
# Purpose: Tests for the DWB-485 backfill script (backend/scripts/backfill_session_synthesis.py).
#          Verifies it populates headline+summary+keywords on null-headline closed
#          sessions via _apply_synthesis, is re-runnable safely (no dup keyword
#          rows / skips already-populated), honors --dry-run, and reports counts.
# Caller: pytest
# Callees: backend/scripts/backfill_session_synthesis.py (loaded via importlib),
#          app.models.*
# Data In: per-test db_session + factory fixtures
# Data Out: assertions
# Last Modified: 2026-06-25

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sqlalchemy import func, select

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.entity_keyword import EntityKeyword
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.ticket import TicketStatus

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "backfill_session_synthesis.py"
)


def _load_script():
    """Load the standalone script as a module. Register in sys.modules BEFORE
    exec_module (the importlib + module-resolution gotcha)."""
    spec = importlib.util.spec_from_file_location(
        "backfill_session_synthesis", _SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_session_synthesis"] = mod
    spec.loader.exec_module(mod)
    return mod


backfill = _load_script()


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def closed_null_headline_session(db_session, make_project, make_agent, make_ticket):
    """A closed, null-headline session with enough activity that the synthesizer
    produces a headline (tokens + a completed ticket + an active agent)."""

    def _make():
        project = make_project()
        pid = project["id"]
        agent = make_agent(project_id=pid, role="backend-worker")
        now = _naive_now()
        opened = now - timedelta(hours=2)
        closed = now - timedelta(minutes=30)

        session = DwbSession(
            project_id=pid,
            opened_at=opened,
            closed_at=closed,
            open_method=DwbOpenMethod.regex,
            total_tokens=1500,
            total_time_seconds=5400,
            headline=None,
        )
        db_session.add(session)
        db_session.flush()
        db_session.refresh(session)

        # A ticket completed inside the window -> keywords + completed bullet.
        ticket = make_ticket(
            project_id=pid,
            title="Migration of the entity_keywords schema",
            description="entity_keywords migration work",
        )
        from app.models.ticket import Ticket

        trow = db_session.get(Ticket, ticket["id"])
        trow.status = TicketStatus.done
        trow.completed_at = closed - timedelta(minutes=10)
        # Active agent in the window so agents_active > 0.
        db_session.add(
            HookSession(
                session_id=f"cc-backfill-{session.id}",
                project_id=pid,
                agent_id=agent["id"],
                start_time=opened + timedelta(minutes=5),
                end_time=closed - timedelta(minutes=5),
                status=HookSessionStatus.completed,
                session_type=HookSessionType.teammate,
                total_tokens=1500,
                dwb_session_id=session.id,
            )
        )
        db_session.flush()
        return session

    return _make


def _keyword_count(db, session_id):
    return db.execute(
        select(func.count(EntityKeyword.id))
        .where(EntityKeyword.entity_type == "dwb_session")
        .where(EntityKeyword.entity_id == session_id)
    ).scalar()


class TestRunBackfill:
    def test_populates_target_session(self, db_session, closed_null_headline_session):
        s = closed_null_headline_session()
        result = backfill.run_backfill(db_session, session_ids=[s.id])
        assert result["targeted"] == 1
        assert result["populated"] == 1
        assert result["failed"] == 0
        db_session.refresh(s)
        assert s.headline is not None
        assert s.summary is not None
        assert _keyword_count(db_session, s.id) > 0

    def test_rerun_skips_already_populated_no_dup_keywords(
        self, db_session, closed_null_headline_session
    ):
        s = closed_null_headline_session()
        backfill.run_backfill(db_session, session_ids=[s.id])
        count_after_first = _keyword_count(db_session, s.id)

        # Second run: the session now has a headline, so it is skipped, and the
        # keyword row count must not grow (re-runnable safety per AC).
        result2 = backfill.run_backfill(db_session, session_ids=[s.id])
        assert result2["targeted"] == 0
        assert result2["populated"] == 0
        assert any(
            sk["id"] == s.id and "headline" in sk["reason"]
            for sk in result2["skipped"]
        )
        assert _keyword_count(db_session, s.id) == count_after_first

    def test_dry_run_writes_nothing(self, db_session, closed_null_headline_session):
        s = closed_null_headline_session()
        result = backfill.run_backfill(db_session, session_ids=[s.id], dry_run=True)
        assert result["dry_run"] is True
        assert result["targeted"] == 1
        assert result["populated"] == 1  # would-populate count
        db_session.refresh(s)
        assert s.headline is None  # nothing written
        assert _keyword_count(db_session, s.id) == 0

    def test_skips_missing_and_open(self, db_session, make_project):
        project = make_project()
        now = _naive_now()
        open_session = DwbSession(
            project_id=project["id"],
            opened_at=now - timedelta(minutes=10),
            closed_at=None,
            open_method=DwbOpenMethod.regex,
        )
        db_session.add(open_session)
        db_session.flush()
        db_session.refresh(open_session)

        result = backfill.run_backfill(
            db_session, session_ids=[open_session.id, 99999999]
        )
        assert result["targeted"] == 0
        reasons = {sk["id"]: sk["reason"] for sk in result["skipped"]}
        assert reasons[open_session.id] == "still open"
        assert reasons[99999999] == "not found"

    def test_all_null_headline_sweep(self, db_session, closed_null_headline_session):
        s1 = closed_null_headline_session()
        s2 = closed_null_headline_session()
        result = backfill.run_backfill(db_session, all_null_headline=True)
        assert result["targeted"] >= 2
        assert s1.id in result["populated_ids"]
        assert s2.id in result["populated_ids"]

    def test_force_regenerates_already_headlined(
        self, db_session, closed_null_headline_session
    ):
        # First pass populates + sets a headline.
        s = closed_null_headline_session()
        backfill.run_backfill(db_session, session_ids=[s.id])
        db_session.refresh(s)
        headline_before = s.headline
        assert headline_before is not None

        # Without force it is skipped; with force it is re-synthesized (DWB-499
        # stopword-refresh path). Headline is preserved; keyword rows are
        # rewritten in place (no duplication).
        skipped = backfill.run_backfill(db_session, session_ids=[s.id])
        assert skipped["targeted"] == 0

        forced = backfill.run_backfill(db_session, session_ids=[s.id], force=True)
        assert forced["targeted"] == 1
        db_session.refresh(s)
        assert s.headline == headline_before  # headline preserved
        assert _keyword_count(db_session, s.id) > 0
