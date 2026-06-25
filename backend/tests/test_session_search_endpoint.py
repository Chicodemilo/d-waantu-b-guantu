# Path: tests/test_session_search_endpoint.py
# File: test_session_search_endpoint.py
# Created: 2026-06-25
# Purpose: Tests for DWBG-011 - GET /api/sessions/search. Covers relevance
#          ordering, keyword-boost reordering, each facet (project/agent/epic/
#          date range), cross-project vs scoped, and empty/blank/unmatched q
#          behavior, plus the slim result shape (snippet + keyword chips).
# Caller: pytest
# Callees: GET /api/sessions/search, app.services.dwb_session_search
# Data In: committed project/session/hook_session/ticket/keyword rows
# Data Out: assertions on the ranked JSON result list
# Last Modified: 2026-06-25

"""DWBG-011: cross-session search endpoint.

MySQL FULLTEXT (MATCH ... AGAINST) cannot see rows inserted in the SAME
uncommitted transaction, so the conftest rollback-isolated db_session is
unusable for search. Every test here drives a `recall_world` fixture that
COMMITS its rows on a dedicated session and deletes them in teardown, so the
data is FULLTEXT-visible to the request the TestClient makes (committed rows are
visible across connections) and nothing leaks between tests.
"""

from datetime import datetime, timedelta

import pytest

from app.models.agent import Agent
from app.models.dwb_session import DwbSession, DwbCloseMethod, DwbCloseReason, DwbOpenMethod
from app.models.entity_keyword import EntityKeyword
from app.models.epic import Epic
from app.models.hook_session import HookSession
from app.models.project import Project
from app.models.sprint import Sprint, SprintStatus
from app.models.ticket import Ticket, TicketStatus


def _naive_now():
    return datetime.utcnow().replace(microsecond=0)


@pytest.fixture
def recall_world():
    """Build a committed graph for search tests, cleaned up in teardown.

    Returns a builder object exposing helpers that COMMIT immediately:
      .project()                          -> project_id
      .agent()                            -> agent_id
      .session(project_id, ...)           -> session_id (commits)
      .link_hook(session_id, agent_id)    -> attach a hook_session for an agent
      .epic_ticket_in_window(session, ...) -> epic_id (ticket completed in window)
    Tracks every committed id and deletes it on teardown (children first).
    """
    from tests.conftest import TestingSession

    db = TestingSession()
    created = {
        "hook_sessions": [],
        "tickets": [],
        "sprints": [],
        "keywords": [],
        "dwb_sessions": [],
        "epics": [],
        "agents": [],
        "projects": [],
    }
    counter = {"n": 0}

    def _uniq():
        counter["n"] += 1
        return counter["n"]

    class Builder:
        def project(self):
            n = _uniq()
            p = Project(prefix=f"RCL{n}", name=f"recall project {n}")
            db.add(p)
            db.commit()
            created["projects"].append(p.id)
            return p.id

        def agent(self):
            n = _uniq()
            a = Agent(name=f"recall-agent-{n}", role="backend-worker", api_key=f"rcl-key-{n}")
            db.add(a)
            db.commit()
            created["agents"].append(a.id)
            return a.id

        def session(
            self,
            project_id,
            *,
            headline=None,
            summary=None,
            narrative=None,
            opened_offset_minutes=10,
            closed_offset_minutes=0,
        ):
            now = _naive_now()
            row = DwbSession(
                project_id=project_id,
                opened_at=now - timedelta(minutes=opened_offset_minutes),
                closed_at=now - timedelta(minutes=closed_offset_minutes),
                open_method=DwbOpenMethod.regex,
                close_method=DwbCloseMethod.regex,
                close_reason=DwbCloseReason.explicit,
                headline=headline,
                summary=summary,
                narrative=narrative,
            )
            db.add(row)
            db.commit()
            created["dwb_sessions"].append(row.id)
            return row.id

        def add_keywords(self, session_id, pairs):
            for kw, w in pairs:
                row = EntityKeyword(
                    entity_type="dwb_session",
                    entity_id=session_id,
                    keyword=kw,
                    weight=w,
                    source="session_synth",
                )
                db.add(row)
                db.commit()
                created["keywords"].append(row.id)

        def link_hook(self, session_id, agent_id, project_id):
            n = _uniq()
            hs = HookSession(
                session_id=f"rcl-hook-{n}",
                agent_id=agent_id,
                project_id=project_id,
                dwb_session_id=session_id,
                start_time=_naive_now() - timedelta(minutes=9),
                end_time=_naive_now() - timedelta(minutes=1),
                total_tokens=100,
            )
            db.add(hs)
            db.commit()
            created["hook_sessions"].append(hs.id)
            return hs.id

        def epic_ticket_in_window(self, project_id, session_id):
            """Create an epic + sprint + a ticket completed inside the session's
            window, returning the epic_id (for the epic_id facet)."""
            sess = db.get(DwbSession, session_id)
            n = _uniq()
            epic = Epic(project_id=project_id, name=f"recall epic {n}")
            db.add(epic)
            db.commit()
            created["epics"].append(epic.id)
            sprint = Sprint(
                project_id=project_id,
                epic_id=epic.id,
                name=f"recall sprint {n}",
                sprint_number=n,
                status=SprintStatus.completed,
            )
            db.add(sprint)
            db.commit()
            created["sprints"].append(sprint.id)
            # completed_at squarely inside [opened_at, closed_at]
            mid = sess.opened_at + (sess.closed_at - sess.opened_at) / 2
            t = Ticket(
                project_id=project_id,
                sprint_id=sprint.id,
                epic_id=epic.id,
                ticket_number=n,
                ticket_key=f"RCL-{n}",
                title="recall ticket",
                status=TicketStatus.done,
                completed_at=mid,
            )
            db.add(t)
            db.commit()
            created["tickets"].append(t.id)
            return epic.id

    try:
        yield Builder()
    finally:
        from sqlalchemy import text as _text

        for table, ids in (
            ("hook_sessions", created["hook_sessions"]),
            ("tickets", created["tickets"]),
            ("sprints", created["sprints"]),
            ("entity_keywords", created["keywords"]),
            ("dwb_sessions", created["dwb_sessions"]),
            ("epics", created["epics"]),
            ("agents", created["agents"]),
            ("projects", created["projects"]),
        ):
            for _id in ids:
                db.execute(_text(f"DELETE FROM {table} WHERE id = :id"), {"id": _id})
        db.commit()
        db.close()


class TestValidation:
    def test_missing_q_is_422(self, client):
        assert client.get("/api/sessions/search").status_code == 422

    def test_blank_q_is_422(self, client):
        r = client.get("/api/sessions/search", params={"q": "   "})
        assert r.status_code == 422

    def test_unmatched_q_returns_empty_list(self, client, recall_world):
        pid = recall_world.project()
        recall_world.session(pid, headline="postgres vacuum tuning")
        r = client.get("/api/sessions/search", params={"q": "zzzznomatchterm"})
        assert r.status_code == 200
        assert r.json() == []


class TestRelevanceOrdering:
    def test_more_relevant_session_ranks_first(self, client, recall_world):
        pid = recall_world.project()
        strong = recall_world.session(
            pid,
            headline="kafka consumer rebalance debugging session",
            summary={"lead": "traced kafka partition rebalance churn for kafka consumers"},
            opened_offset_minutes=5,
        )
        weak = recall_world.session(
            pid,
            headline="frontend pagination refactor with one kafka mention",
            summary={"lead": "extracted a paginator hook; touched kafka once"},
            opened_offset_minutes=30,
        )
        r = client.get("/api/sessions/search", params={"q": "kafka rebalance consumer"})
        assert r.status_code == 200
        ids = [row["id"] for row in r.json()]
        assert strong in ids and weak in ids
        assert ids.index(strong) < ids.index(weak), (
            "the session with denser matching prose must rank above the sparse one"
        )

    def test_recency_breaks_relevance_ties(self, client, recall_world):
        pid = recall_world.project()
        # Identical prose -> identical FULLTEXT relevance; newer opened_at wins.
        older = recall_world.session(
            pid, headline="autovacuum threshold rollout", opened_offset_minutes=120
        )
        newer = recall_world.session(
            pid, headline="autovacuum threshold rollout", opened_offset_minutes=5
        )
        r = client.get("/api/sessions/search", params={"q": "autovacuum threshold rollout"})
        ids = [row["id"] for row in r.json()]
        assert ids.index(newer) < ids.index(older)


class TestKeywordBoost:
    def test_keyword_boost_lifts_a_session(self, client, recall_world):
        """Two sessions with similar prose; the one whose mined keywords align
        with the query gets a higher score and outranks."""
        pid = recall_world.project()
        boosted = recall_world.session(
            pid,
            headline="recall layer search work",
            summary={"lead": "did recall layer search work"},
            opened_offset_minutes=10,
        )
        plain = recall_world.session(
            pid,
            headline="recall layer search work",
            summary={"lead": "did recall layer search work"},
            opened_offset_minutes=8,
        )
        # Heavy keyword weight on the boosted session for a query term.
        recall_world.add_keywords(boosted, [("recall", 50)])
        recall_world.add_keywords(plain, [("unrelated", 1)])

        r = client.get("/api/sessions/search", params={"q": "recall layer search"})
        rows = {row["id"]: row for row in r.json()}
        assert rows[boosted]["keyword_boost"] == 50.0
        assert rows[plain]["keyword_boost"] == 0.0
        assert rows[boosted]["score"] > rows[plain]["score"]
        ids = [row["id"] for row in r.json()]
        assert ids.index(boosted) < ids.index(plain)

    def test_result_carries_keyword_chips_and_snippet(self, client, recall_world):
        pid = recall_world.project()
        sid = recall_world.session(
            pid,
            headline="observability dashboards rollout",
            summary={"lead": "shipped grafana observability dashboards"},
        )
        recall_world.add_keywords(sid, [("observability", 7), ("grafana", 3)])
        r = client.get("/api/sessions/search", params={"q": "observability dashboards"})
        row = next(x for x in r.json() if x["id"] == sid)
        assert row["snippet"]
        chips = {c["keyword"]: c["weight"] for c in row["keywords"]}
        assert chips == {"observability": 7, "grafana": 3}


class TestFacets:
    def test_project_scope_excludes_other_projects(self, client, recall_world):
        p1 = recall_world.project()
        p2 = recall_world.project()
        s1 = recall_world.session(p1, headline="distinctiveterm alpha work")
        s2 = recall_world.session(p2, headline="distinctiveterm beta work")

        # Cross-project: both present.
        cross = client.get("/api/sessions/search", params={"q": "distinctiveterm"}).json()
        cross_ids = {row["id"] for row in cross}
        assert s1 in cross_ids and s2 in cross_ids

        # Scoped to p1: only s1.
        scoped = client.get(
            "/api/sessions/search", params={"q": "distinctiveterm", "project_id": p1}
        ).json()
        scoped_ids = {row["id"] for row in scoped}
        assert scoped_ids == {s1}

    def test_agent_facet(self, client, recall_world):
        pid = recall_world.project()
        a = recall_world.agent()
        worked = recall_world.session(pid, headline="agentfacet payments migration")
        other = recall_world.session(pid, headline="agentfacet billing migration")
        recall_world.link_hook(worked, a, pid)

        r = client.get(
            "/api/sessions/search", params={"q": "agentfacet migration", "agent_id": a}
        )
        ids = {row["id"] for row in r.json()}
        assert ids == {worked}, "agent facet must return only sessions that agent worked"

    def test_epic_facet(self, client, recall_world):
        pid = recall_world.project()
        # Non-overlapping windows: the epic ticket completes inside in_epic's
        # window only. not_in_epic ran much earlier so the ticket's completed_at
        # is outside its window. (The facet is window-based, matching the rollup
        # aggregates convention - a ticket completed in a span matches every
        # session whose window covers that instant, so the windows must be
        # disjoint for an exclusive assertion.)
        # not_in_epic: a fully-past window [now-600, now-500] that does not
        # cover the epic ticket's completed_at (mid of in_epic's [now-10, now]).
        not_in_epic = recall_world.session(
            pid,
            headline="epicfacet unrelated session",
            opened_offset_minutes=600,
            closed_offset_minutes=500,
        )
        in_epic = recall_world.session(
            pid, headline="epicfacet search substrate", opened_offset_minutes=10
        )
        epic_id = recall_world.epic_ticket_in_window(pid, in_epic)

        r = client.get(
            "/api/sessions/search", params={"q": "epicfacet", "epic_id": epic_id}
        )
        ids = {row["id"] for row in r.json()}
        assert ids == {in_epic}

    def test_date_range_facet(self, client, recall_world):
        pid = recall_world.project()
        recent = recall_world.session(
            pid, headline="daterange recent rollout", opened_offset_minutes=10
        )
        old = recall_world.session(
            pid, headline="daterange old rollout", opened_offset_minutes=60 * 48
        )
        # from = 1 hour ago -> excludes the 48h-old session.
        cutoff = (_naive_now() - timedelta(hours=1)).isoformat()
        r = client.get(
            "/api/sessions/search", params={"q": "daterange rollout", "from": cutoff}
        )
        ids = {row["id"] for row in r.json()}
        assert recent in ids
        assert old not in ids
