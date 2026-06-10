# Path: tests/test_jira_epic_dwb363.py
# File: test_jira_epic_dwb363.py
# Created: 2026-06-10
# Purpose: Tests for DWB-363 - 12th Jira table column (jira_epic_key + jira_epic_name) end-to-end
# Caller: pytest
# Callees: app.services.jira._extract_epic_key, app.services.jira_sync.run_sync,
#          GET /api/projects/{id}/jira-tickets, app.models.jira_ticket_snapshot.JiraTicketSnapshot
# Data In: synthetic Jira-linked project, FakeReadOnlyJira with epic + linked-issue payloads
# Data Out: Assertions on extraction paths (parent + legacy customfield), batched epic-name fetch (no N+1),
#           list endpoint shape, search hits both fields, sort works on key, NULL handling.
# Last Modified: 2026-06-10

"""DWB-363 coverage.

The unified Jira table gains a 12th column showing the Jira epic the
issue belongs to. End-to-end pinning:

  1. _extract_epic_key uses parent.key when parent.fields.issuetype is
     Epic (modern Jira / Roadvantage shape; probed live 2026-06-10).
  2. Legacy fallback: when parent isn't an Epic but the issue has the
     legacy "Epic Link" customfield (JIRA_EPIC_LINK_CUSTOMFIELD,
     default customfield_10014) as a bare string key.
  3. None when neither path yields an epic.
  4. jira_sync resolves epic NAMES via a SINGLE batched fetch (no N+1)
     after the linked-issues batch. Number of Jira calls scales with
     epic count, not ticket count.
  5. List endpoint serves both columns on every row; pre-DWB-363 rows
     with NULL pass through clean.
  6. Search hits both jira_epic_key and jira_epic_name.
  7. Sort works on jira_epic_key.
"""

import pytest

from app.services import jira as jira_service
from app.services import jira_sync


# Re-use the read-only Jira fake from the DWB-342/356/362 suites.
_READ_METHODS = frozenset({
    "batch_get_issues", "get_issue", "list_projects", "search_issues",
    "get_active_sprints", "get_sprint_issues",
})


class _FakeReadOnlyJira:
    """Records batch_get_issues calls so a test can assert how many
    Jira fetches a single run_sync() invocation made (DWB-363: at most
    2 - linked issues + unique epic keys)."""

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


def _raw_issue_with_epic_parent(key: str, epic_key: str | None,
                                  issue_type: str = "Story"):
    """Build a raw Jira issue payload where parent is an Epic (modern
    Jira / Roadvantage shape)."""
    fields = {
        "summary": f"summary of {key}",
        "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
        "assignee": {"displayName": "Alice"},
        "reporter": {"displayName": "Bob"},
        "issuetype": {"name": issue_type},
        "priority": {"name": "Medium"},
        "created": "2026-05-01T12:00:00.000+0000",
        "updated": "2026-06-01T12:00:00.000+0000",
    }
    if epic_key:
        fields["parent"] = {
            "key": epic_key,
            "fields": {"issuetype": {"name": "Epic"}},
        }
    return {"key": key, "id": "id-" + key, "fields": fields}


def _normalized_issue(key, *, epic_key=None, issue_type="Story", summary=None):
    """Build a normalized-shape issue (post _normalize_issue) for sync
    tests. Mirrors the keys jira_sync._normalize_jira_payload reads."""
    return {
        "key": key,
        "id": "id-" + key,
        "summary": summary or f"summary of {key}",
        "status": "In Progress",
        "status_category": "In Progress",
        "assignee": "Alice",
        "reporter": "Bob",
        "issue_type": issue_type,
        "parent_key": epic_key,
        "parent_type": "Epic" if epic_key else None,
        "priority": "Medium",
        "created": "2026-05-01T12:00:00.000+0000",
        "updated": "2026-06-01T12:00:00.000+0000",
        "sprint_name": None,
        "epic_key": epic_key,
    }


# ---------------------------------------------------------------------------
# 1. _extract_epic_key paths
# ---------------------------------------------------------------------------


class TestExtractEpicKey:
    def test_parent_is_epic_returns_parent_key(self):
        """Modern Jira / Roadvantage path: parent.key + Epic issue type."""
        raw = _raw_issue_with_epic_parent("POR-1", epic_key="POR-100")
        out = jira_service._normalize_issue(raw)
        assert out["epic_key"] == "POR-100"

    def test_parent_is_story_returns_none(self):
        """Sub-task with a Story parent (not Epic) - the extractor
        returns None for now. One-hop resolution stays out of scope here
        (the rollup_by_epic helper covers it for the rollup endpoint)."""
        raw = {
            "key": "POR-2", "id": "id-2",
            "fields": {
                "summary": "x",
                "issuetype": {"name": "Sub-task"},
                "parent": {
                    "key": "POR-99",
                    "fields": {"issuetype": {"name": "Story"}},
                },
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["epic_key"] is None

    def test_no_parent_returns_none(self):
        """Stand-alone task: no parent, no epic. None."""
        raw = {
            "key": "POR-3", "id": "id-3",
            "fields": {"summary": "x", "issuetype": {"name": "Task"}},
        }
        out = jira_service._normalize_issue(raw)
        assert out["epic_key"] is None

    def test_legacy_customfield_string_fallback(self, monkeypatch):
        """Legacy Jira: no parent, but customfield_10014 carries the
        Epic Link as a string key. Extractor falls back to that."""
        monkeypatch.setattr(
            jira_service.settings, "JIRA_EPIC_LINK_CUSTOMFIELD",
            "customfield_10014",
        )
        raw = {
            "key": "POR-4", "id": "id-4",
            "fields": {
                "summary": "x",
                "issuetype": {"name": "Story"},
                "customfield_10014": "POR-200",
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["epic_key"] == "POR-200"

    def test_parent_path_preferred_over_customfield(self, monkeypatch):
        """When both signals exist, parent-as-Epic wins (more authoritative
        on modern Jira). The customfield value is ignored."""
        monkeypatch.setattr(
            jira_service.settings, "JIRA_EPIC_LINK_CUSTOMFIELD",
            "customfield_10014",
        )
        raw = {
            "key": "POR-5", "id": "id-5",
            "fields": {
                "summary": "x",
                "issuetype": {"name": "Story"},
                "parent": {
                    "key": "POR-PARENT",
                    "fields": {"issuetype": {"name": "Epic"}},
                },
                "customfield_10014": "POR-DIFFERENT",
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["epic_key"] == "POR-PARENT"


# ---------------------------------------------------------------------------
# 2. Sync writes epic_key + batched epic-name resolution
# ---------------------------------------------------------------------------


@pytest.fixture
def jira_project(db_session):
    from app.models.project import Project
    p = Project(
        prefix="J363",
        name="DWB-363 Test",
        jira_base_url="https://example.atlassian.net",
        jira_project_key="POR",
        repo_path="/tmp/j363",
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
    counter = [400]

    def _make(jira_key, title="row"):
        counter[0] += 1
        t = Ticket(
            project_id=jira_project.id, epic_id=epic.id, sprint_id=sprint.id,
            ticket_number=counter[0], ticket_key=f"J363-{counter[0]}",
            title=title, status=TicketStatus.in_progress,
            jira_issue_key=jira_key,
        )
        db_session.add(t)
        db_session.flush()
        return t

    return _make


class TestSyncWritesEpicAndResolvesName:
    def test_sync_writes_epic_key_and_name_from_batched_fetch(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """End-to-end: linked tickets point at POR-100 + POR-200 epics.
        Sync writes epic_key per snapshot AND resolves epic_name via
        the batched epic-summary fetch."""
        from app.models.jira_ticket_snapshot import JiraTicketSnapshot

        make_linked_ticket("POR-A")
        make_linked_ticket("POR-B")
        make_linked_ticket("POR-C")

        fake = _FakeReadOnlyJira({
            "POR-A": _normalized_issue("POR-A", epic_key="POR-100"),
            "POR-B": _normalized_issue("POR-B", epic_key="POR-200"),
            "POR-C": _normalized_issue("POR-C", epic_key="POR-100"),
            # Epic summaries the batched lookup will fetch.
            "POR-100": _normalized_issue(
                "POR-100", issue_type="Epic", summary="First Epic",
            ),
            "POR-200": _normalized_issue(
                "POR-200", issue_type="Epic", summary="Second Epic",
            ),
        })
        jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )

        snaps = {
            s.jira_issue_key: s
            for s in db_session.query(JiraTicketSnapshot).all()
        }
        assert snaps["POR-A"].jira_epic_key == "POR-100"
        assert snaps["POR-A"].jira_epic_name == "First Epic"
        assert snaps["POR-B"].jira_epic_key == "POR-200"
        assert snaps["POR-B"].jira_epic_name == "Second Epic"
        assert snaps["POR-C"].jira_epic_key == "POR-100"
        assert snaps["POR-C"].jira_epic_name == "First Epic"

    def test_epic_lookup_is_batched_no_n_plus_one(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """1 batch_get_issues for linked tickets + 1 batch_get_issues for
        unique epic keys = 2 calls total, regardless of ticket count.

        Pins the N+1 prevention - if a future regression switches to
        per-issue epic fetches, this assertion fires."""
        for i in range(5):
            make_linked_ticket(f"POR-T{i}")

        fake = _FakeReadOnlyJira({
            f"POR-T{i}": _normalized_issue(
                f"POR-T{i}", epic_key="POR-100" if i % 2 == 0 else "POR-200",
            )
            for i in range(5)
        } | {
            "POR-100": _normalized_issue("POR-100", issue_type="Epic", summary="A"),
            "POR-200": _normalized_issue("POR-200", issue_type="Epic", summary="B"),
        })
        jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )

        batch_calls = [c for c in fake.calls if c[0] == "batch_get_issues"]
        assert len(batch_calls) == 2, (
            f"expected 2 batch_get_issues calls (linked + epics), "
            f"got {len(batch_calls)}: {batch_calls}"
        )

    def test_no_epic_keys_means_no_epic_lookup_call(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """When NO linked ticket has an epic, the sync still works and
        skips the epic-lookup batch call entirely (1 call total)."""
        make_linked_ticket("POR-NOEPIC1")
        make_linked_ticket("POR-NOEPIC2")
        fake = _FakeReadOnlyJira({
            "POR-NOEPIC1": _normalized_issue("POR-NOEPIC1", epic_key=None),
            "POR-NOEPIC2": _normalized_issue("POR-NOEPIC2", epic_key=None),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        batch_calls = [c for c in fake.calls if c[0] == "batch_get_issues"]
        assert len(batch_calls) == 1

    def test_missing_epic_summary_leaves_name_none_but_key_persists(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """If the epic-summary batch returns no entry for the epic key
        (deleted, restricted, whatever), snapshot keeps epic_key and
        leaves epic_name None. Per-row write doesn't fail."""
        from app.models.jira_ticket_snapshot import JiraTicketSnapshot

        make_linked_ticket("POR-X")
        fake = _FakeReadOnlyJira({
            "POR-X": _normalized_issue("POR-X", epic_key="POR-GONE"),
            # POR-GONE intentionally absent - the batched epic-summary
            # call returns empty for it.
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-X",
        ).one()
        assert snap.jira_epic_key == "POR-GONE"
        assert snap.jira_epic_name is None


# ---------------------------------------------------------------------------
# 3. List endpoint serves the new columns
# ---------------------------------------------------------------------------


class TestListEndpointServesEpicColumns:
    def _seed(self, db_session, jira_project, make_linked_ticket):
        make_linked_ticket("POR-A")
        make_linked_ticket("POR-B")
        fake = _FakeReadOnlyJira({
            "POR-A": _normalized_issue("POR-A", epic_key="POR-100"),
            "POR-B": _normalized_issue("POR-B", epic_key="POR-200"),
            "POR-100": _normalized_issue("POR-100", issue_type="Epic", summary="Alpha Epic"),
            "POR-200": _normalized_issue("POR-200", issue_type="Epic", summary="Beta Epic"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

    def test_every_row_carries_epic_key_and_name(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, jira_project, make_linked_ticket)
        r = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        for row in rows:
            assert "jira_epic_key" in row
            assert "jira_epic_name" in row
        by_jira = {row["jira_key"]: row for row in rows}
        assert by_jira["POR-A"]["jira_epic_key"] == "POR-100"
        assert by_jira["POR-A"]["jira_epic_name"] == "Alpha Epic"
        assert by_jira["POR-B"]["jira_epic_key"] == "POR-200"
        assert by_jira["POR-B"]["jira_epic_name"] == "Beta Epic"

    def test_pre_dwb363_row_serves_null_clean(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        from datetime import datetime
        from app.models.jira_ticket_snapshot import JiraTicketSnapshot

        ticket = make_linked_ticket("POR-OLD")
        snap = JiraTicketSnapshot(
            ticket_id=ticket.id,
            jira_issue_key="POR-OLD",
            jira_status="In Progress",
            last_synced_at=datetime.utcnow(),
            # jira_epic_key + jira_epic_name intentionally omitted.
        )
        db_session.add(snap)
        db_session.flush()
        r = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        match = next(row for row in r.json()["rows"] if row["jira_key"] == "POR-OLD")
        assert match["jira_epic_key"] is None
        assert match["jira_epic_name"] is None


# ---------------------------------------------------------------------------
# 4. Search hits epic_key + epic_name
# ---------------------------------------------------------------------------


class TestSearchHitsEpic:
    def _seed(self, db_session, jira_project, make_linked_ticket):
        make_linked_ticket("POR-1")
        make_linked_ticket("POR-2")
        make_linked_ticket("POR-3")
        fake = _FakeReadOnlyJira({
            "POR-1": _normalized_issue("POR-1", epic_key="POR-100"),
            "POR-2": _normalized_issue("POR-2", epic_key="POR-200"),
            "POR-3": _normalized_issue("POR-3", epic_key=None),
            "POR-100": _normalized_issue(
                "POR-100", issue_type="Epic", summary="Gemini Claims",
            ),
            "POR-200": _normalized_issue(
                "POR-200", issue_type="Epic", summary="Fraud Detection",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

    def test_search_by_epic_key(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, jira_project, make_linked_ticket)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "POR-200"},
        )
        body = r.json()
        # The substring matches both POR-2 (ticket) and POR-200 (epic).
        # POR-2 has epic POR-200; POR-200 itself is not in the listed
        # tickets (not linked). So one row matches.
        assert body["total"] == 1
        assert body["rows"][0]["jira_key"] == "POR-2"
        assert body["rows"][0]["jira_epic_key"] == "POR-200"

    def test_search_by_epic_name_token(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, jira_project, make_linked_ticket)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "Gemini"},
        )
        body = r.json()
        assert body["total"] == 1
        assert body["rows"][0]["jira_epic_name"] == "Gemini Claims"


# ---------------------------------------------------------------------------
# 5. Sort by jira_epic_key
# ---------------------------------------------------------------------------


class TestSortByEpicKey:
    def test_sort_asc(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-A")
        make_linked_ticket("POR-B")
        make_linked_ticket("POR-C")
        fake = _FakeReadOnlyJira({
            "POR-A": _normalized_issue("POR-A", epic_key="POR-300"),
            "POR-B": _normalized_issue("POR-B", epic_key="POR-100"),
            "POR-C": _normalized_issue("POR-C", epic_key="POR-200"),
            "POR-100": _normalized_issue("POR-100", issue_type="Epic", summary="E1"),
            "POR-200": _normalized_issue("POR-200", issue_type="Epic", summary="E2"),
            "POR-300": _normalized_issue("POR-300", issue_type="Epic", summary="E3"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"sort": "jira_epic_key", "order": "asc"},
        )
        keys = [row["jira_epic_key"] for row in r.json()["rows"]]
        assert keys == ["POR-100", "POR-200", "POR-300"]
