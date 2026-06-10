# Path: tests/test_jira_issue_type_dwb362.py
# File: test_jira_issue_type_dwb362.py
# Created: 2026-06-10
# Purpose: Tests for DWB-362 - 11th Jira-table column (jira_issue_type) end-to-end
# Caller: pytest
# Callees: app.services.jira_sync, GET /api/projects/{id}/jira-tickets,
#          app.models.jira_ticket_snapshot.JiraTicketSnapshot
# Data In: Jira-linked synthetic project, FakeReadOnlyJira injected client, normalized issue payloads
# Data Out: Assertions on snapshot column write, list row shape, search hit, sort whitelist, NULL handling
# Last Modified: 2026-06-10

"""DWB-362 coverage.

The unified Jira table gains an 11th column showing the Jira issue type
(Task / Sub-task / Bug / Story / Epic / etc.). End-to-end pinning:

  1. The sync writes issuetype.name from the normalized payload onto
     JiraTicketSnapshot.jira_issue_type.
  2. The list endpoint serves the column on every row.
  3. Search hits jira_issue_type (typing "Bug" filters to bugs).
  4. Sort works on jira_issue_type.
  5. NULL handles cleanly: snapshots created before the DWB-362 sync ran
     (or unmatched rows) serve None and the list endpoint passes that
     through without crashing.
"""

import pytest

from app.models.jira_ticket_snapshot import JiraTicketSnapshot
from app.services import jira_sync


# Re-use the read-only Jira fake from the DWB-342/356 suites.
_READ_METHODS = frozenset({
    "batch_get_issues", "get_issue", "list_projects", "search_issues",
    "get_active_sprints", "get_sprint_issues",
})


class _FakeReadOnlyJira:
    def __init__(self, issues_by_key):
        self._issues_by_key = issues_by_key
        self.calls = []

    def __getattr__(self, name):
        if name not in _READ_METHODS:
            raise AttributeError(
                f"FakeReadOnlyJira refuses '{name}' - read-only contract.",
            )
        def _stub(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "batch_get_issues":
                keys = args[0] if args else kwargs.get("issue_keys", [])
                return [self._issues_by_key[k] for k in keys if k in self._issues_by_key]
            return []
        return _stub


def _normalized_issue(key, *, issue_type="Task", status="In Progress",
                       assignee="Alice", reporter="Bob", summary="synthetic",
                       sprint_name=None):
    """Normalized issue dict matching `app.services.jira._normalize_issue`
    output post-DWB-356, including the DWB-362 issue_type key."""
    return {
        "key": key,
        "id": "id-" + key,
        "summary": summary,
        "status": status,
        "status_category": "In Progress",
        "assignee": assignee,
        "reporter": reporter,
        "issue_type": issue_type,
        "parent_key": None,
        "parent_type": None,
        "priority": "Medium",
        "created": "2026-05-01T12:00:00.000+0000",
        "updated": "2026-06-01T12:00:00.000+0000",
        "sprint_name": sprint_name,
    }


@pytest.fixture
def jira_project(db_session):
    from app.models.project import Project
    p = Project(
        prefix="J362",
        name="DWB-362 Test",
        jira_base_url="https://example.atlassian.net",
        jira_project_key="POR",
        repo_path="/tmp/j362",
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def make_linked_ticket(db_session, jira_project):
    from app.models.epic import Epic, EpicStatus
    from app.models.sprint import Sprint, SprintStatus
    from app.models.ticket import Ticket, TicketStatus

    epic = Epic(project_id=jira_project.id, name="E1", status=EpicStatus.open)
    db_session.add(epic)
    db_session.flush()
    sprint = Sprint(
        project_id=jira_project.id, epic_id=epic.id, name="S1",
        sprint_number=1, status=SprintStatus.active,
    )
    db_session.add(sprint)
    db_session.flush()
    counter = [300]

    def _make(jira_key, title="row"):
        counter[0] += 1
        t = Ticket(
            project_id=jira_project.id, epic_id=epic.id, sprint_id=sprint.id,
            ticket_number=counter[0], ticket_key=f"J362-{counter[0]}",
            title=title, status=TicketStatus.in_progress,
            jira_issue_key=jira_key,
        )
        db_session.add(t)
        db_session.flush()
        return t

    return _make


# ---------------------------------------------------------------------------
# 1. Snapshot column write
# ---------------------------------------------------------------------------


class TestSnapshotWritesIssueType:
    def test_sync_persists_issue_type_to_snapshot(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-T")
        fake = _FakeReadOnlyJira({"POR-T": _normalized_issue("POR-T", issue_type="Task")})
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-T",
        ).one()
        assert snap.jira_issue_type == "Task"

    def test_changed_issue_type_counts_as_updated(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-CH")
        fake_v1 = _FakeReadOnlyJira({
            "POR-CH": _normalized_issue("POR-CH", issue_type="Task"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake_v1)

        fake_v2 = _FakeReadOnlyJira({
            "POR-CH": _normalized_issue("POR-CH", issue_type="Bug"),
        })
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake_v2,
        )
        assert counts["updated"] == 1
        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-CH",
        ).one()
        assert snap.jira_issue_type == "Bug"


# ---------------------------------------------------------------------------
# 2. List endpoint serves the column
# ---------------------------------------------------------------------------


class TestListEndpointServesIssueType:
    def _seed(self, db_session, jira_project, make_linked_ticket):
        make_linked_ticket("POR-TASK")
        make_linked_ticket("POR-BUG")
        make_linked_ticket("POR-SUB")
        fake = _FakeReadOnlyJira({
            "POR-TASK": _normalized_issue("POR-TASK", issue_type="Task"),
            "POR-BUG":  _normalized_issue("POR-BUG",  issue_type="Bug"),
            "POR-SUB":  _normalized_issue("POR-SUB",  issue_type="Sub-task"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

    def test_every_row_carries_jira_issue_type(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, jira_project, make_linked_ticket)
        r = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        assert len(rows) == 3
        for row in rows:
            assert "jira_issue_type" in row
            assert row["jira_issue_type"] is not None

        # The three values round-trip.
        type_by_key = {row["jira_key"]: row["jira_issue_type"] for row in rows}
        assert type_by_key == {
            "POR-TASK": "Task", "POR-BUG": "Bug", "POR-SUB": "Sub-task",
        }

    def test_pre_dwb362_row_serves_null_issue_type(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        """A snapshot row written before the DWB-362 sync ran would have
        jira_issue_type=NULL. The list endpoint serves None through
        without crashing - the UI null-guards with a '-' placeholder."""
        ticket = make_linked_ticket("POR-OLD")
        # Seed a snapshot directly without going through the sync,
        # simulating a pre-DWB-362 cache state.
        from datetime import datetime
        snap = JiraTicketSnapshot(
            ticket_id=ticket.id,
            jira_issue_key="POR-OLD",
            jira_status="In Progress",
            jira_title="old row",
            last_synced_at=datetime.utcnow(),
            # jira_issue_type intentionally omitted -> NULL.
        )
        db_session.add(snap)
        db_session.flush()

        r = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        assert r.status_code == 200
        matching = [row for row in r.json()["rows"] if row["jira_key"] == "POR-OLD"]
        assert len(matching) == 1
        assert matching[0]["jira_issue_type"] is None


# ---------------------------------------------------------------------------
# 3. Search hits issue_type
# ---------------------------------------------------------------------------


class TestSearchHitsIssueType:
    def test_search_token_filters_to_matching_type(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-A")
        make_linked_ticket("POR-B")
        make_linked_ticket("POR-C")
        fake = _FakeReadOnlyJira({
            "POR-A": _normalized_issue("POR-A", issue_type="Task"),
            "POR-B": _normalized_issue("POR-B", issue_type="Bug"),
            "POR-C": _normalized_issue("POR-C", issue_type="Story"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "Bug"},
        )
        body = r.json()
        assert body["total"] == 1
        assert body["rows"][0]["jira_issue_type"] == "Bug"

    def test_search_token_substring_matches_subtask(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        """Substring 'sub' against jira_issue_type='Sub-task' must match."""
        make_linked_ticket("POR-Z")
        make_linked_ticket("POR-Y")
        fake = _FakeReadOnlyJira({
            "POR-Z": _normalized_issue("POR-Z", issue_type="Sub-task"),
            "POR-Y": _normalized_issue("POR-Y", issue_type="Task"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "sub"},
        )
        body = r.json()
        assert body["total"] == 1
        assert body["rows"][0]["jira_issue_type"] == "Sub-task"


# ---------------------------------------------------------------------------
# 4. Sort whitelist accepts jira_issue_type
# ---------------------------------------------------------------------------


class TestSortByIssueType:
    def test_sort_asc_by_issue_type(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-TS")
        make_linked_ticket("POR-BG")
        make_linked_ticket("POR-EP")
        fake = _FakeReadOnlyJira({
            "POR-TS": _normalized_issue("POR-TS", issue_type="Task"),
            "POR-BG": _normalized_issue("POR-BG", issue_type="Bug"),
            "POR-EP": _normalized_issue("POR-EP", issue_type="Epic"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"sort": "jira_issue_type", "order": "asc"},
        )
        assert r.status_code == 200, r.text
        types = [row["jira_issue_type"] for row in r.json()["rows"]]
        assert types == sorted(types)
        # Bug < Epic < Task alphabetically.
        assert types == ["Bug", "Epic", "Task"]

    def test_sort_descending_inverts(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-1")
        make_linked_ticket("POR-2")
        fake = _FakeReadOnlyJira({
            "POR-1": _normalized_issue("POR-1", issue_type="Task"),
            "POR-2": _normalized_issue("POR-2", issue_type="Bug"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"sort": "jira_issue_type", "order": "desc"},
        )
        types = [row["jira_issue_type"] for row in r.json()["rows"]]
        assert types == ["Task", "Bug"]
