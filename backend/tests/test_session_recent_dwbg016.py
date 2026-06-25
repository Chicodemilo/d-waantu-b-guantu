# Path: tests/test_session_recent_dwbg016.py
# File: test_session_recent_dwbg016.py
# Created: 2026-06-25
# Purpose: Backend tests for GET /api/sessions/recent (DWBG-016 dependency) — cross-project
#          newest-first slim rows (id, project_id, headline, opened_at, closed_at,
#          total_tokens, keywords), limit/offset paging, keyword chips, and that "recent"
#          is not parsed as a session id by the /{session_id} catch-all.
# Caller: pytest
# Callees: /api/sessions/recent endpoint, DwbSession + EntityKeyword models
# Data In: per-test db_session + make_project fixture + hand-rolled session rows
# Data Out: assertions on the recent-sessions response
# Last Modified: 2026-06-25

"""DWBG-016 dependency — cross-project recent sessions endpoint, backend coverage."""

from datetime import datetime, timedelta

from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.entity_keyword import EntityKeyword


def _naive(ts):
    return ts.replace(microsecond=0)


def _make_session(db_session, project_id, *, opened_at, headline=None, tokens=0):
    # Closed by default: the single-active UNIQUE index forbids two OPEN sessions
    # per project, and recent-list rows are overwhelmingly closed sessions anyway.
    row = DwbSession(
        project_id=project_id,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=5),
        open_method=DwbOpenMethod.regex,
        headline=headline,
        total_tokens=tokens,
    )
    db_session.add(row)
    db_session.flush()
    return row


class TestRecentSessions:
    def test_newest_first_cross_project(
        self, client, db_session, make_project
    ):
        p1 = make_project()
        p2 = make_project()
        base = _naive(datetime.utcnow())
        old = _make_session(db_session, p1["id"], opened_at=base - timedelta(hours=3),
                            headline="older one")
        mid = _make_session(db_session, p2["id"], opened_at=base - timedelta(hours=2),
                            headline="middle one")
        new = _make_session(db_session, p1["id"], opened_at=base - timedelta(hours=1),
                            headline="newest one")
        db_session.commit()

        r = client.get("/api/sessions/recent?limit=50")
        assert r.status_code == 200
        ids = [row["id"] for row in r.json()]
        # newest-first ordering; spans both projects.
        pos = {sid: ids.index(sid) for sid in (old.id, mid.id, new.id)}
        assert pos[new.id] < pos[mid.id] < pos[old.id]

    def test_slim_row_shape(self, client, db_session, make_project):
        p = make_project()
        row = _make_session(
            db_session, p["id"], opened_at=_naive(datetime.utcnow()),
            headline="shape check", tokens=123,
        )
        db_session.add(EntityKeyword(
            entity_type="dwb_session", entity_id=row.id,
            keyword="recall", weight=4, source="test",
        ))
        db_session.commit()

        r = client.get("/api/sessions/recent?limit=50")
        item = next(x for x in r.json() if x["id"] == row.id)
        assert set(item.keys()) == {
            "id", "project_id", "headline", "opened_at", "closed_at",
            "total_tokens", "keywords",
        }
        assert item["project_id"] == p["id"]
        assert item["total_tokens"] == 123
        assert item["keywords"][0]["keyword"] == "recall"

    def test_limit_and_offset(self, client, db_session, make_project):
        p = make_project()
        base = _naive(datetime.utcnow())
        rows = [
            _make_session(db_session, p["id"], opened_at=base - timedelta(minutes=i),
                          headline=f"s{i}")
            for i in range(5)
        ]
        db_session.commit()
        recent_ids = {row.id for row in rows}

        page1 = client.get("/api/sessions/recent?limit=2&offset=0").json()
        page2 = client.get("/api/sessions/recent?limit=2&offset=2").json()
        assert len(page1) == 2
        # Pages do not overlap.
        assert {x["id"] for x in page1}.isdisjoint({x["id"] for x in page2})

    def test_recent_not_parsed_as_session_id(self, client):
        # The /{session_id} catch-all must not swallow "recent" (which would 404
        # or 422). A 200 list proves the /recent route is registered first.
        r = client.get("/api/sessions/recent")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
