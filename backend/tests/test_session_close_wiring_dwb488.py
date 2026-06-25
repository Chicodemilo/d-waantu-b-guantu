# Path: tests/test_session_close_wiring_dwb488.py
# File: test_session_close_wiring_dwb488.py
# Created: 2026-06-25
# Purpose: Integration tests for DWB-488 - close-path WIRING of the DWB-484
#          synthesizer across EVERY close method and the idle sweeper, plus the
#          DWB-493 close->read round-trip. Deliberately complementary, not
#          duplicative: the pure units live in test_session_synthesizer.py (23)
#          and test_keyword_extraction.py (21); the existing wiring file
#          test_session_synthesis_wiring_dwb484.py already covers idle_timeout
#          (direct + sweeper), ai_confident supplied-headline, and idempotency,
#          and test_session_read_exposure_dwb493.py already covers the batched
#          read shape + no-N+1. This file fills the per-close-path matrix
#          (regex / slash / ai_asked were uncovered), the supplied-headline
#          branch across ALL methods, the regex null-headline regression, the
#          sweeper keyword-row assertion, and the synthesize->persist->read API
#          round-trip that the hand-seeded 493 tests never exercise.
# Caller: pytest
# Callees: app.services.dwb_session (close_session, sweep_idle_sessions), the
#          /api/sessions read endpoints
# Data In: per-test db_session + factory fixtures + hand-rolled session/hook/ticket rows
# Data Out: assertions on persisted headline / summary / EntityKeyword rows and read-API shape
# Last Modified: 2026-06-25

"""DWB-488: synthesizer close-path wiring across every method + the read round-trip.

close_session is the single close funnel (the close endpoint and
sweep_idle_sessions both route through it). DWB-484 proved the funnel synthesizes
for idle_timeout + ai_confident; these tests assert the SAME triad (synthesized
headline, structured summary, weighted keyword rows) lands for the remaining
close methods (regex / slash / ai_asked), for the supplied-headline branch on
every method, and that the persisted data surfaces through the DWB-493 read API.
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
from app.services.dwb_session import close_session, sweep_idle_sessions


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


# The five live close methods DWB-488 must cover. ai_classifier is a retired
# tombstone (DWB-402) - no new sessions are stamped with it, so it is out of
# scope. idle_timeout closes carry reason=idle; the explicit-intent methods
# (regex / slash / ai_confident / ai_asked) carry reason=explicit.
CLOSE_PATHS = [
    (DwbCloseMethod.regex, DwbCloseReason.explicit),
    (DwbCloseMethod.slash, DwbCloseReason.explicit),
    (DwbCloseMethod.idle_timeout, DwbCloseReason.idle),
    (DwbCloseMethod.ai_confident, DwbCloseReason.explicit),
    (DwbCloseMethod.ai_asked, DwbCloseReason.explicit),
]
CLOSE_PATH_IDS = [m.value for m, _ in CLOSE_PATHS]


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
    """A ticket completed inside the session window with a meaningful title.

    The ticket_key is kept verbatim by the keyword extractor (DWB-900), so a
    closed session always mines at least its tickets into the corpus - giving
    the wiring assertions a deterministic keyword to look for.
    """

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
    def _make(project_id, *, session_id, dwb_session_id, agent_id=None, tokens=1000,
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


class TestEveryCloseMethodSynthesizes:
    """One assertion matrix per live close method: closing WITH activity and
    NO supplied headline must persist the full synthesized triad.

    Fills the gap left by DWB-484, which exercised only idle_timeout (direct +
    sweeper) and ai_confident. regex / slash / ai_asked were never wired-tested.
    """

    @pytest.mark.parametrize("method, reason", CLOSE_PATHS, ids=CLOSE_PATH_IDS)
    def test_close_persists_headline_summary_keywords(
        self, db_session, make_project, open_session, completed_ticket, method, reason
    ):
        project = make_project()
        sess = open_session(project["id"])
        completed_ticket(
            project["id"], key="DWB-700", title="close path wiring corpus distillation"
        )

        close_session(
            db_session, sess, close_method=method, close_reason=reason
        )

        # Headline synthesized (the caller supplied none) - never left blank.
        assert sess.headline is not None
        assert sess.headline.strip() != ""
        assert sess.headline.lower() != "none"
        # Structured summary JSON persisted on dwb_session.summary.
        assert isinstance(sess.summary, dict)
        assert sess.summary.get("lead")
        assert isinstance(sess.summary.get("sections"), list)
        # Weighted keyword rows, correctly tagged to this session.
        kws = _keywords_for(db_session, sess.id)
        assert len(kws) > 0
        for kw in kws:
            assert kw.entity_type == "dwb_session"
            assert kw.entity_id == sess.id
            assert kw.keyword
            assert kw.weight >= 1
        # Sanity: the method actually stamped as requested.
        assert sess.close_method == method


class TestSuppliedHeadlinePreservedEveryMethod:
    """A caller-supplied headline must be preserved verbatim on every close
    method (DWB-484 only proved this for ai_confident), while summary +
    keywords are still synthesized."""

    @pytest.mark.parametrize("method, reason", CLOSE_PATHS, ids=CLOSE_PATH_IDS)
    def test_supplied_headline_not_overwritten(
        self, db_session, make_project, open_session, completed_ticket, method, reason
    ):
        project = make_project()
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-701", title="explicit headline branch")
        supplied = f"Operator headline for {method.value}"

        close_session(
            db_session, sess, close_method=method, close_reason=reason,
            headline=supplied,
        )

        assert sess.headline == supplied
        assert isinstance(sess.summary, dict)
        assert len(_keywords_for(db_session, sess.id)) > 0


class TestNullHeadlineRegression:
    """The bug DWB-484 fixed: a close WITH activity used to leave headline NULL.
    DWB-484 covered the idle path; this nails the regex path explicitly so the
    regression is guarded on both of the methods the bug was reported against."""

    def test_regex_close_with_activity_yields_headline_not_null(
        self, db_session, make_project, open_session, completed_ticket
    ):
        project = make_project()
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-702", title="regex null headline regression")

        close_session(
            db_session, sess,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )

        assert sess.headline is not None
        assert sess.headline.strip() != ""


class TestKeywordWiringEndToEnd:
    """Proves the corpus -> extractor -> persisted-rows pipeline runs THROUGH
    the close funnel (not just in the isolated unit): the completed ticket's
    key surfaces verbatim as a keyword row after a real close."""

    def test_ticket_key_surfaces_as_keyword_after_close(
        self, db_session, make_project, open_session, completed_ticket
    ):
        project = make_project()
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-703", title="verbatim ticket key in corpus")

        close_session(
            db_session, sess,
            close_method=DwbCloseMethod.slash,
            close_reason=DwbCloseReason.explicit,
        )

        keywords = {kw.keyword for kw in _keywords_for(db_session, sess.id)}
        assert "DWB-703" in keywords


class TestIdleSweeperPersistsKeywords:
    """The idle sweeper routes through close_session, so it must persist the
    full triad. DWB-484's sweeper test asserted headline + summary only; this
    adds the weighted-keyword-row assertion for the sweeper path."""

    def test_sweep_idle_persists_keyword_rows(
        self, db_session, make_project, open_session, completed_ticket
    ):
        project = make_project()
        # Opened 120 min ago so it is idle past a 60 min threshold.
        sess = open_session(project["id"], opened_offset_minutes=120)
        completed_ticket(
            project["id"], key="DWB-704", title="idle sweeper keyword rows",
            completed_offset_minutes=100,
        )

        closed_count = sweep_idle_sessions(db_session, idle_minutes=60)

        assert closed_count >= 1
        db_session.refresh(sess)
        assert sess.closed_at is not None
        assert sess.close_method == DwbCloseMethod.idle_timeout
        assert sess.headline is not None and sess.headline.strip() != ""
        assert isinstance(sess.summary, dict)
        kws = _keywords_for(db_session, sess.id)
        assert len(kws) > 0
        assert all(k.weight >= 1 for k in kws)


class TestCloseThenReadRoundTrip:
    """DWB-493 read tests hand-seed EntityKeyword rows; none close a real
    session and read it back. This asserts the synthesize-on-close output
    surfaces through the detail + list read endpoints end to end."""

    def test_detail_surfaces_synthesized_summary_and_keywords(
        self, client, db_session, make_project, open_session, completed_ticket
    ):
        project = make_project()
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-705", title="round trip detail read")
        close_session(
            db_session, sess,
            close_method=DwbCloseMethod.regex,
            close_reason=DwbCloseReason.explicit,
        )

        r = client.get(f"/api/sessions/{sess.id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["summary"], dict)
        assert body["summary"].get("lead")
        # Keywords surface as {keyword, weight}, sorted weight desc.
        assert len(body["keywords"]) > 0
        weights = [k["weight"] for k in body["keywords"]]
        assert weights == sorted(weights, reverse=True)
        assert "DWB-705" in {k["keyword"] for k in body["keywords"]}

    def test_list_surfaces_synthesized_summary_and_keywords(
        self, client, db_session, make_project, open_session, completed_ticket
    ):
        project = make_project()
        sess = open_session(project["id"])
        completed_ticket(project["id"], key="DWB-706", title="round trip list read")
        close_session(
            db_session, sess,
            close_method=DwbCloseMethod.slash,
            close_reason=DwbCloseReason.explicit,
        )

        r = client.get(f"/api/projects/{project['id']}/sessions")
        assert r.status_code == 200, r.text
        rows = {row["id"]: row for row in r.json()}
        assert sess.id in rows
        row = rows[sess.id]
        assert isinstance(row["summary"], dict)
        assert "DWB-706" in {k["keyword"] for k in row["keywords"]}
