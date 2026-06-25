# Path: tests/test_session_read_exposure_dwb493.py
# File: test_session_read_exposure_dwb493.py
# Created: 2026-06-25
# Purpose: Tests for DWB-493 - the session list + detail read endpoints surface
#          `summary` (JSON) and weighted `keywords` (sorted weight desc), with
#          the list batching the keyword fetch (no N+1).
# Caller: pytest
# Callees: GET /api/projects/{id}/sessions, GET /api/sessions/{id}
# Data In: per-test db_session + factory fixtures + seeded DwbSession/EntityKeyword rows
# Data Out: assertions on the JSON read shape
# Last Modified: 2026-06-25

"""DWB-493: read-exposure of summary + keywords on session list/detail."""

from datetime import datetime, timedelta

import pytest

from app.models.dwb_session import DwbSession, DwbOpenMethod
from app.models.entity_keyword import EntityKeyword


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def seed_session(db_session):
    def _make(project_id, *, summary=None, opened_offset_minutes=10, closed=True):
        now = _naive_now()
        # Default closed: only one OPEN session per project is allowed (unique
        # constraint), so list tests that need several sessions use closed rows.
        row = DwbSession(
            project_id=project_id,
            opened_at=now - timedelta(minutes=opened_offset_minutes),
            closed_at=(now if closed else None),
            open_method=DwbOpenMethod.regex,
            open_phrase="open the session",
            summary=summary,
        )
        db_session.add(row)
        db_session.flush()
        return row

    return _make


@pytest.fixture
def seed_keywords(db_session):
    def _make(session_id, pairs):
        for kw, weight in pairs:
            db_session.add(EntityKeyword(
                entity_type="dwb_session", entity_id=session_id,
                keyword=kw, weight=weight, source="session_synth",
            ))
        db_session.flush()

    return _make


class TestDetailReadShape:
    def test_detail_exposes_summary_and_sorted_keywords(
        self, client, db_session, make_project, seed_session, seed_keywords
    ):
        project = make_project()
        summary = {"lead": "did things", "sections": [{"title": "Tickets", "bullets": ["1 done"]}]}
        sess = seed_session(project["id"], summary=summary)
        seed_keywords(sess.id, [("tmux", 5), ("DWB-1", 50), ("alpha", 5)])

        r = client.get(f"/api/sessions/{sess.id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"] == summary
        # Sorted weight desc, then keyword asc on ties (alpha before tmux).
        assert body["keywords"] == [
            {"keyword": "DWB-1", "weight": 50},
            {"keyword": "alpha", "weight": 5},
            {"keyword": "tmux", "weight": 5},
        ]

    def test_detail_empty_keywords_and_null_summary(
        self, client, make_project, seed_session
    ):
        project = make_project()
        sess = seed_session(project["id"])
        r = client.get(f"/api/sessions/{sess.id}")
        assert r.status_code == 200
        assert r.json()["summary"] is None
        assert r.json()["keywords"] == []


class TestListReadShape:
    def test_list_exposes_summary_and_keywords_per_row(
        self, client, db_session, make_project, seed_session, seed_keywords
    ):
        project = make_project()
        s1 = seed_session(project["id"], summary={"lead": "one", "sections": []},
                          opened_offset_minutes=5)
        s2 = seed_session(project["id"], summary={"lead": "two", "sections": []},
                          opened_offset_minutes=20)
        seed_keywords(s1.id, [("aaa", 2), ("bbb", 9)])
        seed_keywords(s2.id, [("ccc", 1)])

        r = client.get(f"/api/projects/{project['id']}/sessions")
        assert r.status_code == 200, r.text
        rows = {row["id"]: row for row in r.json()}
        assert rows[s1.id]["summary"] == {"lead": "one", "sections": []}
        assert rows[s1.id]["keywords"] == [
            {"keyword": "bbb", "weight": 9},
            {"keyword": "aaa", "weight": 2},
        ]
        assert rows[s2.id]["keywords"] == [{"keyword": "ccc", "weight": 1}]

    def test_list_keyword_fetch_is_batched_single_query(
        self, client, db_session, make_project, seed_session, seed_keywords
    ):
        """The page's keywords must load in ONE query, not per-row (no N+1)."""
        project = make_project()
        sessions = [seed_session(project["id"], opened_offset_minutes=i + 1)
                    for i in range(5)]
        for s in sessions:
            seed_keywords(s.id, [("k", 1)])

        from app.routers import dwb_sessions as mod
        calls = {"n": 0}
        original = mod._keywords_by_session

        def counting(db, ids):
            calls["n"] += 1
            return original(db, ids)

        mod._keywords_by_session = counting
        try:
            r = client.get(f"/api/projects/{project['id']}/sessions")
        finally:
            mod._keywords_by_session = original
        assert r.status_code == 200
        # Exactly one batched call for the whole page.
        assert calls["n"] == 1

    def test_list_row_with_no_keywords_is_empty_list(
        self, client, make_project, seed_session
    ):
        project = make_project()
        seed_session(project["id"])
        r = client.get(f"/api/projects/{project['id']}/sessions")
        assert r.status_code == 200
        assert r.json()[0]["keywords"] == []
