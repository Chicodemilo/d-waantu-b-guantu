# Path: tests/test_session_search_substrate.py
# File: test_session_search_substrate.py
# Created: 2026-06-25
# Purpose: Tests for DWBG-010 - the dwb_sessions.search_text STORED generated
#          column + ftx_dwb_sessions_search FULLTEXT index. Asserts the column
#          and index exist in lat_test, that the generated column flattens
#          headline + summary + narrative, and that a MATCH query ranks the
#          right row.
# Caller: pytest
# Callees: sqlalchemy.inspect / text, DwbSession model
# Data In: per-test db_session + factory fixtures + seeded DwbSession rows
# Data Out: assertions on schema + MATCH relevance
# Last Modified: 2026-06-25

"""DWBG-010: FULLTEXT search substrate over session write-ups.

The schema is created in lat_test by Base.metadata.create_all (conftest), which
reflects the ORM. So these tests prove the ORM declarations (the Computed
generated column + the mysql_prefix='FULLTEXT' Index) actually materialize the
intended MySQL schema, AND that a MATCH ... AGAINST query over it works.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect, text

from app.models.dwb_session import DwbOpenMethod, DwbSession

# The conftest db_session runs inside a single transaction that is rolled back
# per test. InnoDB FULLTEXT indexes are maintained through a commit-time cache
# flush, so a MATCH ... AGAINST query does NOT see rows inserted in the SAME
# uncommitted transaction. Schema + generated-column assertions are fine in the
# rolled-back session (no MATCH needed), but the relevance tests below must run
# against COMMITTED data. The `committed_sessions` fixture commits its rows on a
# dedicated connection and deletes them (plus the throwaway project) in teardown,
# so it never leaks across tests despite escaping the rollback isolation.


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def seed_session(db_session):
    def _make(
        project_id,
        *,
        headline=None,
        summary=None,
        narrative=None,
        opened_offset_minutes=10,
        closed=True,
    ):
        now = _naive_now()
        row = DwbSession(
            project_id=project_id,
            opened_at=now - timedelta(minutes=opened_offset_minutes),
            closed_at=(now if closed else None),
            open_method=DwbOpenMethod.regex,
            headline=headline,
            summary=summary,
            narrative=narrative,
        )
        db_session.add(row)
        db_session.flush()
        # search_text is a STORED generated column - MySQL computes it on write,
        # so refresh to pull the materialized value back into the ORM instance.
        db_session.refresh(row)
        return row

    return _make


class TestSchema:
    def test_search_text_is_stored_generated_column(self, db_session):
        """search_text exists and is a STORED GENERATED column (not a plain
        column the app would have to maintain)."""
        row = db_session.execute(
            text(
                "SELECT EXTRA FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = 'lat_test' "
                "AND TABLE_NAME = 'dwb_sessions' "
                "AND COLUMN_NAME = 'search_text'"
            )
        ).fetchone()
        assert row is not None, "search_text column missing from dwb_sessions"
        assert "STORED GENERATED" in row.EXTRA.upper()

    def test_fulltext_index_exists(self, db_session):
        """The ftx_dwb_sessions_search index exists and is of type FULLTEXT."""
        rows = db_session.execute(
            text(
                "SELECT DISTINCT INDEX_TYPE FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = 'lat_test' "
                "AND TABLE_NAME = 'dwb_sessions' "
                "AND INDEX_NAME = 'ftx_dwb_sessions_search'"
            )
        ).fetchall()
        assert rows, "ftx_dwb_sessions_search index missing"
        assert any(r.INDEX_TYPE.upper() == "FULLTEXT" for r in rows)

    def test_index_reflected_via_inspector(self, db_session):
        """Belt-and-braces: the SQLAlchemy inspector also reports the index on
        the search_text column, so ORM-driven schema management sees it."""
        insp = inspect(db_session.get_bind())
        idx = next(
            (
                ix
                for ix in insp.get_indexes("dwb_sessions")
                if ix["name"] == "ftx_dwb_sessions_search"
            ),
            None,
        )
        assert idx is not None
        assert idx["column_names"] == ["search_text"]


class TestGeneratedColumnContent:
    def test_search_text_flattens_headline_summary_narrative(
        self, db_session, make_project, seed_session
    ):
        project = make_project()
        sess = seed_session(
            project["id"],
            headline="kafka consumer rebalance debugging",
            summary={"lead": "traced the partition assignment churn", "sections": []},
            narrative={"lead": "decision: pin the static group membership"},
        )
        st = sess.search_text
        assert st is not None
        # Prose from all three fields is present.
        assert "kafka consumer rebalance debugging" in st
        assert "partition assignment churn" in st
        assert "static group membership" in st

    def test_search_text_non_null_when_all_fields_null(
        self, db_session, make_project, seed_session
    ):
        """CONCAT_WS + COALESCE keeps search_text a (possibly empty) string, not
        NULL, even when headline/summary/narrative are all NULL."""
        project = make_project()
        sess = seed_session(project["id"])
        assert sess.search_text is not None
        assert sess.search_text.strip() == ""


@pytest.fixture
def committed_sessions():
    """Create a throwaway project + a set of COMMITTED sessions, yield their ids,
    then delete them in teardown.

    MATCH ... AGAINST cannot see rows inserted in an uncommitted transaction, so
    the rollback-isolated db_session fixture is unusable for relevance tests.
    This fixture commits on its own connection/session (from the conftest test
    engine) and cleans up afterward, so it does not leak across tests.

    Yields a dict: {"project_id", "by_headline": {headline: session_id}}.
    """
    from app.models.project import Project
    from tests.conftest import TestingSession

    session = TestingSession()
    created_ids: list[int] = []
    project = Project(prefix="FTXSRCH", name="FULLTEXT search test project")
    session.add(project)
    session.commit()
    project_id = project.id

    def _add(headline, summary=None, narrative=None, opened_offset_minutes=10):
        now = _naive_now()
        row = DwbSession(
            project_id=project_id,
            opened_at=now - timedelta(minutes=opened_offset_minutes),
            closed_at=now,
            open_method=DwbOpenMethod.regex,
            headline=headline,
            summary=summary,
            narrative=narrative,
        )
        session.add(row)
        session.commit()
        created_ids.append(row.id)
        return row.id

    state = {"project_id": project_id, "add": _add}
    try:
        yield state
    finally:
        for sid in created_ids:
            session.execute(
                text("DELETE FROM dwb_sessions WHERE id = :id"), {"id": sid}
            )
        session.execute(
            text("DELETE FROM projects WHERE id = :id"), {"id": project_id}
        )
        session.commit()
        session.close()


class TestMatchQuery:
    def test_match_returns_the_relevant_row(self, db_session, committed_sessions):
        """A MATCH(search_text) AGAINST query returns the session whose prose
        contains the distinctive term and outranks the unrelated one."""
        add = committed_sessions["add"]
        hit = add(
            "postgres vacuum autotuning rollout",
            summary={"lead": "tuned autovacuum thresholds on the orders table"},
            opened_offset_minutes=5,
        )
        miss = add(
            "frontend pagination component refactor",
            summary={"lead": "extracted a reusable paginator hook"},
            opened_offset_minutes=20,
        )

        rows = db_session.execute(
            text(
                "SELECT id, "
                "MATCH(search_text) AGAINST(:q IN NATURAL LANGUAGE MODE) AS rel "
                "FROM dwb_sessions "
                "WHERE id IN (:a, :b) "
                "ORDER BY rel DESC"
            ),
            {"q": "autovacuum thresholds", "a": hit, "b": miss},
        ).fetchall()

        by_id = {r.id: r.rel for r in rows}
        assert by_id[hit] > 0, "expected the matching session to score > 0"
        assert by_id[hit] > by_id[miss], (
            "the autovacuum session must outrank the unrelated frontend session"
        )

    def test_match_boolean_mode_finds_distinctive_tokens(
        self, db_session, committed_sessions
    ):
        """Boolean-mode MATCH finds a session by distinctive tokens embedded in
        the summary prose (mirrors how DWBG-011 will query)."""
        add = committed_sessions["add"]
        sid = add(
            "shipped the recall layer search endpoint",
            summary={"lead": "wired the FULLTEXT ranking query for recall"},
        )
        rows = db_session.execute(
            text(
                "SELECT id FROM dwb_sessions "
                "WHERE MATCH(search_text) AGAINST(:q IN BOOLEAN MODE)"
            ),
            {"q": "+recall +endpoint"},
        ).fetchall()
        assert sid in {r.id for r in rows}
