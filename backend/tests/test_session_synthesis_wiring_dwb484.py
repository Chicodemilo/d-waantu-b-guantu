# Path: tests/test_session_synthesis_wiring_dwb484.py
# File: test_session_synthesis_wiring_dwb484.py
# Created: 2026-06-25
# Purpose: Integration tests for DWB-484 - close_session synthesizes + persists
#          headline / summary / weighted keywords on every close path, including
#          the idle sweeper. Verifies the null-headline fix, supplied-headline
#          preservation, and idempotency on reopen/re-close.
# Caller: pytest
# Callees: app.services.dwb_session (close_session, sweep_idle_sessions, reopen_session)
# Data In: per-test db_session + factory fixtures + hand-rolled session/hook/ticket rows
# Data Out: assertions on session.headline / session.summary / EntityKeyword rows
# Last Modified: 2026-06-25

"""DWB-484: synthesizer wiring into the close funnel.

close_session is the single close funnel (the close endpoint and
sweep_idle_sessions both route through it), so these tests exercise it directly.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.dwb_session import (
    DwbCloseMethod,
    DwbCloseReason,
    DwbOpenMethod,
    DwbSession,
)
from app.models.entity_keyword import EntityKeyword
from app.models.hook_session import HookSession, HookSessionStatus, HookSessionType
from app.models.ticket import Ticket, TicketStatus
from app.services.dwb_session import (
    close_session,
    reopen_session,
    sweep_idle_sessions,
)


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def open_session(db_session):
    def _make(project_id, *, opened_offset_minutes=30):
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
def completed_ticket(db_session, make_ticket):
    """A ticket completed inside the session window with a meaningful title."""

    def _make(project_id, *, key, title, completed_offset_minutes=10):
        t = make_ticket(project_id=project_id, ticket_key=key, title=title)
        row = db_session.get(Ticket, t["id"])
        row.status = TicketStatus.done
        row.completed_at = _naive_now() - timedelta(minutes=completed_offset_minutes)
        db_session.flush()
        return row

    return _make


@pytest.fixture
def link_hook(db_session):
    def _make(project_id, *, session_id, agent_id, dwb_session_id, tokens=1000,
              start_offset_minutes=20, end_offset_minutes=5):
        now = _naive_now()
        row = HookSession(
            session_id=session_id,
            project_id=project_id,
            agent_id=agent_id,
            start_time=now - timedelta(minutes=start_offset_minutes),
            end_time=now - timedelta(minutes=end_offset_minutes),
            status=HookSessionStatus.completed,
            session_type=HookSessionType.teammate,
            total_tokens=tokens,
            dwb_session_id=dwb_session_id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


def _keywords_for(db_session, session_id):
    return db_session.execute(
        select(EntityKeyword)
        .where(EntityKeyword.entity_type == "dwb_session")
        .where(EntityKeyword.entity_id == session_id)
    ).scalars().all()


class TestNullHeadlineFix:
    def test_idle_close_synthesizes_headline_and_summary(
        self, db_session, make_project, make_agent, open_session,
        completed_ticket, link_hook,
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"])
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-900", title="synthesizer wiring keyword corpus")
        link_hook(project["id"], session_id="cc-900", agent_id=agent["id"],
                  dwb_session_id=sess.id, tokens=5000)

        # Idle-timeout close supplies NO headline - the null-headline bug path.
        close_session(
            db_session, sess,
            close_method=DwbCloseMethod.idle_timeout,
            close_reason=DwbCloseReason.idle,
        )

        assert sess.headline is not None and sess.headline.strip() != ""
        assert isinstance(sess.summary, dict)
        assert sess.summary["lead"]
        assert isinstance(sess.summary["sections"], list)
        # Keyword rows mined from the corpus, tagged source=session_synth.
        kws = _keywords_for(db_session, sess.id)
        assert len(kws) > 0
        assert all(k.source == "session_synth" for k in kws)

    def test_sweep_idle_populates_summary(
        self, db_session, make_project, make_agent, open_session,
        completed_ticket, link_hook,
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"])
        # Opened 120 min ago, idle past a 60 min threshold.
        sess = open_session(project["id"], opened_offset_minutes=120)
        completed_ticket(project["id"], key="DWB-901", title="idle sweeper write up",
                         completed_offset_minutes=90)
        # Last activity must be older than the 60 min idle threshold or the
        # sweeper keeps the session alive.
        link_hook(project["id"], session_id="cc-901", agent_id=agent["id"],
                  dwb_session_id=sess.id, start_offset_minutes=110,
                  end_offset_minutes=90)

        closed = sweep_idle_sessions(db_session, idle_minutes=60)
        assert closed == 1
        assert sess.close_method == DwbCloseMethod.idle_timeout
        assert sess.headline is not None
        assert isinstance(sess.summary, dict)


class TestSuppliedHeadlinePreserved:
    def test_supplied_headline_not_overwritten(
        self, db_session, make_project, make_agent, open_session,
        completed_ticket, link_hook,
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"])
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-902", title="explicit headline case")
        link_hook(project["id"], session_id="cc-902", agent_id=agent["id"],
                  dwb_session_id=sess.id)

        close_session(
            db_session, sess,
            close_method=DwbCloseMethod.ai_confident,
            close_reason=DwbCloseReason.explicit,
            headline="Operator wrote this headline",
        )
        assert sess.headline == "Operator wrote this headline"
        # Summary + keywords still synthesized even when headline supplied.
        assert isinstance(sess.summary, dict)
        assert len(_keywords_for(db_session, sess.id)) > 0


class TestIdempotency:
    def test_reopen_reclose_does_not_duplicate_keywords(
        self, db_session, make_project, make_agent, open_session,
        completed_ticket, link_hook,
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"])
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-903", title="idempotent keyword corpus")
        link_hook(project["id"], session_id="cc-903", agent_id=agent["id"],
                  dwb_session_id=sess.id)

        close_session(db_session, sess,
                      close_method=DwbCloseMethod.idle_timeout,
                      close_reason=DwbCloseReason.idle)
        first = {k.keyword for k in _keywords_for(db_session, sess.id)}
        assert first

        # Reopen then re-close: keyword rows replaced, not appended.
        reopened, conflict = reopen_session(db_session, sess)
        assert conflict is None and reopened is not None
        close_session(db_session, sess,
                      close_method=DwbCloseMethod.idle_timeout,
                      close_reason=DwbCloseReason.idle)
        second = _keywords_for(db_session, sess.id)
        # No duplication: one row per distinct keyword.
        assert len(second) == len({k.keyword for k in second})
        assert {k.keyword for k in second} == first

    def test_already_closed_is_noop(
        self, db_session, make_project, make_agent, open_session,
        completed_ticket, link_hook,
    ):
        project = make_project()
        agent = make_agent(project_id=project["id"])
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-904", title="noop second close")
        link_hook(project["id"], session_id="cc-904", agent_id=agent["id"],
                  dwb_session_id=sess.id)

        close_session(db_session, sess,
                      close_method=DwbCloseMethod.idle_timeout,
                      close_reason=DwbCloseReason.idle)
        count_before = len(_keywords_for(db_session, sess.id))
        headline_before = sess.headline

        # Second close is an early-return no-op: no re-synth, no extra rows.
        close_session(db_session, sess,
                      close_method=DwbCloseMethod.ai_confident,
                      close_reason=DwbCloseReason.explicit,
                      headline="should be ignored")
        assert sess.headline == headline_before
        assert len(_keywords_for(db_session, sess.id)) == count_before
