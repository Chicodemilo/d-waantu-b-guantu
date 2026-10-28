# Path: tests/test_journal_by_id_dwb687.py
# File: test_journal_by_id_dwb687.py
# Created: 2026-10-28 (DWB-687)
# Purpose: Guard GET /api/journal/{id} - that it returns the entry, that a
#          missing id 404s NAMING the entity, and that it never increments
#          retrieval_count while search still does.
# Caller: pytest
# Callees: GET /api/journal/{id}, GET/POST /api/journal, app.services.journal
# Data In: test DB rows via the factory fixtures
# Data Out: Assertions on responses and on persisted retrieval counts
# Last Modified: 2026-10-28 (DWB-687)

"""DWB-687.

The defect was not that an entry could not be fetched. It was that the absence
of a route produced FastAPI's bare `{"detail": "Not Found"}`, which a team lead
read as the entry's absence and reported to the human as a missing journal
entry when the entry was there. So the wording is under test here as much as
the status code is: a 404 that does not name what was not found is the bug.

THE NON-INCREMENT IS THE DELICATE HALF. Asserting a counter did not move is
worth nothing unless the same test can show the counter moving, because a
suite pointed at the wrong row, or at a route that silently 404s, reports
exactly what a correct implementation reports. `test_a_search_does_increment`
exists for that reason alone and should never be deleted as redundant: it is
what makes every assertion of "did not move" in this file mean something.
"""

import pytest

from app.models.journal_entry import JournalEntry
from app.services import journal as journal_svc


@pytest.fixture
def journal_agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


@pytest.fixture
def entry(client, journal_agent):
    r = client.post(
        "/api/journal",
        json={
            "agent_id": journal_agent["id"],
            "body": "the ssh config change that broke the deploy on a Friday",
            "tags": ["ssh", "deploy"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _count_of(db_session, entry_id):
    db_session.expire_all()
    return db_session.get(JournalEntry, entry_id).retrieval_count


class TestReadById:
    def test_returns_the_entry(self, client, entry, journal_agent):
        r = client.get(f"/api/journal/{entry['id']}")
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["id"] == entry["id"]
        assert got["agent_id"] == journal_agent["id"]
        assert got["body"] == entry["body"]
        assert got["tags"] == ["ssh", "deploy"]

    def test_missing_id_404s_naming_the_entity(self, client):
        """The whole defect. A bare 'Not Found' is what made an agent report a
        teammate's entry missing when it was there."""
        r = client.get("/api/journal/99999999")
        assert r.status_code == 404, r.text
        detail = r.json()["detail"]
        assert "journal entry" in detail.lower(), detail
        assert "99999999" in detail, detail
        # The exact string the absence of this route used to produce.
        assert detail != "Not Found"

    def test_a_non_integer_id_does_not_fall_through_to_the_search_route(
        self, client
    ):
        """`/api/journal/abc` must not be answered by GET "" - a path that
        reaches the search handler would be refused for the wrong reason (no
        filter) and teach the caller the wrong lesson."""
        r = client.get("/api/journal/abc")
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["detail"][0]["loc"][-1] == "entry_id", body


class TestTheFetchIsNotCounted:
    """A search increments because the row coming back is evidence it matched a
    question. An addressed fetch is not evidence - the caller already had the
    id - and counting it would let three page loads promote an entry into the
    tier that never decays."""

    def test_a_search_does_increment(self, client, db_session, entry):
        """THE CONTROL. Without this, every non-increment assertion below is
        also what a broken test reports."""
        before = _count_of(db_session, entry["id"])
        r = client.get("/api/journal", params={"term": "ssh config"})
        assert r.status_code == 200, r.text
        assert any(e["id"] == entry["id"] for e in r.json()["entries"])
        assert _count_of(db_session, entry["id"]) == before + 1

    def test_one_fetch_does_not_increment(self, client, db_session, entry):
        before = _count_of(db_session, entry["id"])
        assert client.get(f"/api/journal/{entry['id']}").status_code == 200
        assert _count_of(db_session, entry["id"]) == before

    def test_fetching_past_the_promotion_threshold_does_not_promote(
        self, client, db_session, entry
    ):
        """The consequence that makes this a ruling rather than a preference:
        `retrieval_count` drives journal-to-CORE promotion, so a UI rendering
        an entry on every page load must not be able to earn it a permanent
        tier."""
        for _ in range(journal_svc.PROMOTION_THRESHOLD + 2):
            assert client.get(f"/api/journal/{entry['id']}").status_code == 200

        assert _count_of(db_session, entry["id"]) == 0
        candidates = journal_svc.promotion_candidates(
            db_session, agent_id=entry["agent_id"]
        )
        assert entry["id"] not in [c.id for c in candidates]

    def test_the_response_reports_the_stored_count(
        self, client, db_session, entry
    ):
        """The fetch must not quietly report a different number from the one in
        the database - a read that disagrees with storage about a count whose
        job is to be counted is worse than one that does not show it."""
        client.get("/api/journal", params={"term": "ssh config"})
        stored = _count_of(db_session, entry["id"])
        assert stored == 1
        assert client.get(f"/api/journal/{entry['id']}").json()[
            "retrieval_count"
        ] == stored


class TestTheSearchRuleIsUnchanged:
    """Adding `/{entry_id}` must not shadow or soften GET "". The journal is
    still never read whole."""

    def test_unfiltered_search_is_still_refused(self, client):
        r = client.get("/api/journal")
        assert r.status_code == 422, r.text
        for name in journal_svc.REQUIRED_FILTERS:
            assert name in r.json()["detail"]

    def test_agent_id_alone_is_still_refused(self, client, journal_agent):
        r = client.get("/api/journal", params={"agent_id": journal_agent["id"]})
        assert r.status_code == 422, r.text
        assert "agent_id alone" in r.json()["detail"]
