# Path: tests/test_jira_sync_dwb342.py
# File: test_jira_sync_dwb342.py
# Created: 2026-06-10
# Purpose: Tests for DWB-342 unified Jira table - sync service, endpoints, READ-ONLY invariant
# Caller: pytest
# Callees: app.services.jira_sync, GET /api/projects/{id}/jira-tickets,
#          POST /api/projects/{id}/jira-sync, GET /api/projects/{id}/jira-sync/status
# Data In: synthetic Jira-linked project (not DWB, per spec - first real consumer is FRAUDI),
#          FakeReadOnlyJira injected client with canned issue responses
# Data Out: Assertions on counts/idempotency/ READ-ONLY invariant; endpoint search/sort/pagination/404/400/409
# Last Modified: 2026-06-10

"""DWB-342 coverage.

The unified Jira table replaces /jira and /jira-rollup with one synced
table backed by a per-ticket snapshot cache. The hard rule: NOTHING in
this feature writes to Jira. Tests use a FakeReadOnlyJira injection
that explicitly refuses to expose mutating methods - any attempt to
call ``.transition``, ``.update``, ``.post``, etc. raises AttributeError
loudly. The fake also records every method call so the assertions can
pin the exact READ surface.

The spec's "first real consumer is FRAUDI" note means we set up a
synthetic Jira-linked project via the make_project fixture with a
jira_base_url override - we do NOT touch the live DWB project (id=1).
"""

from datetime import datetime, timedelta

import pytest

from app.models.jira_ticket_snapshot import JiraTicketSnapshot
from app.models.project import JiraSyncStatus
from app.services import jira_sync


# ---------------------------------------------------------------------------
# Fake Jira client - READ-ONLY by construction
# ---------------------------------------------------------------------------


_READ_METHODS = frozenset({
    "batch_get_issues",  # only method jira_sync currently calls
    "get_issue", "list_projects", "search_issues",
    "get_active_sprints", "get_sprint_issues",
})


class FakeReadOnlyJira:
    """Minimal injection seam for jira_sync tests.

    - Constructed with a dict mapping Jira key -> normalized issue dict.
    - batch_get_issues(keys) returns the matching entries; missing keys
      simply don't appear in the output (mirrors real Jira's behavior on
      a key-list JQL search).
    - Every method invocation is recorded in self.calls.
    - Mutating attribute lookups (transition, update_issue, post, delete,
      anything not in _READ_METHODS) raise AttributeError - the
      read-only contract is enforced at the seam, not just by the
      caller's discipline.
    """

    def __init__(self, issues_by_key: dict):
        self._issues_by_key = issues_by_key
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        if name not in _READ_METHODS:
            raise AttributeError(
                f"FakeReadOnlyJira refuses access to '{name}' - DWB-342 "
                f"read-only contract. If you legitimately need a new "
                f"method, add it to _READ_METHODS in the test file "
                f"after confirming it is a read."
            )
        # Anything in the read whitelist returns a recording stub.
        def _stub(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "batch_get_issues":
                keys = args[0] if args else kwargs.get("issue_keys", [])
                return [self._issues_by_key[k] for k in keys if k in self._issues_by_key]
            return []
        return _stub


def _make_jira_issue(
    key: str,
    *,
    status: str = "In Progress",
    assignee: str = "Alice",
    reporter: str = "Bob",
    summary: str = "Do the thing",
    description: str | None = None,
    created: str = "2026-05-01T12:00:00.000+0000",
    updated: str = "2026-06-01T12:00:00.000+0000",
):
    """Build a normalized issue dict matching app.services.jira._normalize_issue
    output shape (the key set jira_sync._normalize_jira_payload reads)."""
    return {
        "key": key,
        "id": "id-" + key,
        "summary": summary,
        "status": status,
        "assignee": assignee,
        "reporter": reporter,
        "description": description,
        "issue_type": "Story",
        "parent_key": None,
        "parent_type": None,
        "priority": "Medium",
        "created": created,
        "updated": updated,
        "sprint_name": None,  # the real client doesn't surface this yet
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def jira_project(client, db_session):
    """A synthetic Jira-linked project. Uses a fresh make_project + sets
    jira_base_url via the model so it's truly isolated from DWB itself."""
    from app.models.project import Project

    p = Project(
        prefix="JRA1",
        name="Synthetic Jira Project",
        jira_base_url="https://example.atlassian.net",
        jira_project_key="POR",
        repo_path="/tmp/jra1",
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def make_linked_ticket(client, db_session, jira_project):
    """Create a DWB ticket linked to a given Jira key under jira_project."""
    from app.models.epic import Epic, EpicStatus
    from app.models.sprint import Sprint, SprintStatus
    from app.models.ticket import Ticket, TicketStatus

    # One shared epic + sprint so the FK chain is satisfied.
    epic = Epic(
        project_id=jira_project.id,
        name="Synthetic Epic",
        status=EpicStatus.open,
    )
    db_session.add(epic)
    db_session.flush()
    sprint = Sprint(
        project_id=jira_project.id,
        epic_id=epic.id,
        name="S1",
        sprint_number=1,
        status=SprintStatus.active,
    )
    db_session.add(sprint)
    db_session.flush()

    _counter = [100]

    def _make(jira_key: str, title: str = "synthetic"):
        _counter[0] += 1
        t = Ticket(
            project_id=jira_project.id,
            epic_id=epic.id,
            sprint_id=sprint.id,
            ticket_number=_counter[0],
            ticket_key=f"JRA1-{_counter[0]}",
            title=title,
            status=TicketStatus.in_progress,
            jira_issue_key=jira_key,
        )
        db_session.add(t)
        db_session.flush()
        return t

    return _make


# ---------------------------------------------------------------------------
# 1. Sync service - happy path, idempotency, counts
# ---------------------------------------------------------------------------


class TestSyncServiceCounts:
    def test_first_sync_adds_snapshots_for_every_linked_ticket(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-1", title="One")
        make_linked_ticket("POR-2", title="Two")
        make_linked_ticket("POR-3", title="Three")

        fake = FakeReadOnlyJira({
            "POR-1": _make_jira_issue("POR-1"),
            "POR-2": _make_jira_issue("POR-2"),
            "POR-3": _make_jira_issue("POR-3"),
        })
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )
        assert counts["added"] == 3
        assert counts["updated"] == 0
        assert counts["unchanged"] == 0
        assert counts["missing"] == []
        assert counts["errors"] == []

        # Snapshots exist + populated.
        snapshots = db_session.query(JiraTicketSnapshot).filter(
            JiraTicketSnapshot.jira_issue_key.in_(["POR-1", "POR-2", "POR-3"])
        ).all()
        assert len(snapshots) == 3
        for s in snapshots:
            assert s.jira_status == "In Progress"
            assert s.jira_assignee == "Alice"
            assert s.last_synced_at is not None

    def test_rerun_with_no_changes_counts_unchanged(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-1")
        fake = FakeReadOnlyJira({"POR-1": _make_jira_issue("POR-1")})
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        # Second run: same fake data, no Jira-side changes.
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )
        assert counts["added"] == 0
        assert counts["updated"] == 0
        assert counts["unchanged"] == 1

    def test_changed_jira_status_counts_as_updated(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-1")
        fake_v1 = FakeReadOnlyJira({"POR-1": _make_jira_issue("POR-1", status="In Progress")})
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake_v1)

        fake_v2 = FakeReadOnlyJira({"POR-1": _make_jira_issue("POR-1", status="Done")})
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake_v2,
        )
        assert counts["added"] == 0
        assert counts["updated"] == 1
        assert counts["unchanged"] == 0

        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-1"
        ).one()
        assert snap.jira_status == "Done"

    def test_missing_jira_key_listed_in_missing(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-EXISTS")
        make_linked_ticket("POR-MISSING")
        fake = FakeReadOnlyJira({"POR-EXISTS": _make_jira_issue("POR-EXISTS")})
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )
        assert counts["added"] == 1
        assert counts["missing"] == ["POR-MISSING"]

    def test_empty_linked_list_returns_clean_zeros(
        self, db_session, jira_project,
    ):
        fake = FakeReadOnlyJira({})
        counts = jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )
        assert counts == {
            "added": 0, "updated": 0, "unchanged": 0,
            "missing": [], "errors": [],
        }


# ---------------------------------------------------------------------------
# 2. READ-ONLY invariant: mock asserts no mutating methods called
# ---------------------------------------------------------------------------


class TestReadOnlyInvariant:
    def test_sync_only_calls_read_methods(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """The fake explodes on any non-read method access; passing this
        test means jira_sync never tried to mutate Jira."""
        make_linked_ticket("POR-1")
        make_linked_ticket("POR-2")
        fake = FakeReadOnlyJira({
            "POR-1": _make_jira_issue("POR-1"),
            "POR-2": _make_jira_issue("POR-2"),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        # Every recorded call must be in the read whitelist.
        method_names = {name for (name, _a, _kw) in fake.calls}
        forbidden = method_names - _READ_METHODS
        assert forbidden == set(), (
            f"jira_sync invoked non-read methods: {forbidden}. "
            f"DWB-342 read-only contract violation."
        )
        # And specifically: batch_get_issues is the one method we expect.
        assert method_names == {"batch_get_issues"}

    def test_attribute_access_to_mutating_method_raises(self):
        """Belt: confirm the fake itself enforces the seam, so a future
        regression in jira_sync that calls .transition() would blow up
        loud rather than silently mutating Jira in production."""
        fake = FakeReadOnlyJira({})
        with pytest.raises(AttributeError, match="read-only contract"):
            _ = fake.transition
        with pytest.raises(AttributeError, match="read-only contract"):
            _ = fake.update_issue
        with pytest.raises(AttributeError, match="read-only contract"):
            _ = fake.post

    def test_sync_does_not_modify_canonical_ticket_rows(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """DWB-342 cache writes go to jira_ticket_snapshots only - the
        canonical tickets table is untouched by the sync. (DWB <- Jira
        status-mapping write-back is a different, pre-existing flow
        that is explicitly out of scope here.)"""
        ticket = make_linked_ticket("POR-1")
        original_status = ticket.status
        original_title = ticket.title

        fake = FakeReadOnlyJira({
            "POR-1": _make_jira_issue(
                "POR-1", status="Done", summary="Jira-side different title",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        db_session.refresh(ticket)
        assert ticket.status == original_status
        assert ticket.title == original_title


# ---------------------------------------------------------------------------
# 3. Concurrency lock + SyncAlreadyRunning
# ---------------------------------------------------------------------------


class TestConcurrencyLock:
    def test_second_call_while_running_raises(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """Simulate a sync already in flight by stamping the project row
        directly, then attempt a second run."""
        from app.models.project import Project

        make_linked_ticket("POR-1")
        # Pretend a sync is in progress.
        jira_project.last_jira_sync_status = JiraSyncStatus.running
        db_session.commit()

        fake = FakeReadOnlyJira({"POR-1": _make_jira_issue("POR-1")})
        with pytest.raises(jira_sync.SyncAlreadyRunning):
            jira_sync.run_sync(
                db_session, jira_project.id, jira_client_override=fake,
            )

    def test_lock_releases_on_success(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-1")
        fake = FakeReadOnlyJira({"POR-1": _make_jira_issue("POR-1")})
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        db_session.refresh(jira_project)
        assert jira_project.last_jira_sync_status == JiraSyncStatus.done

    def test_lock_releases_on_error(
        self, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-1")

        class _Boom:
            def batch_get_issues(self, keys):
                raise RuntimeError("synthetic Jira outage")

        with pytest.raises(RuntimeError, match="synthetic Jira outage"):
            jira_sync.run_sync(
                db_session, jira_project.id, jira_client_override=_Boom(),
            )
        db_session.refresh(jira_project)
        assert jira_project.last_jira_sync_status == JiraSyncStatus.error
        # Counts payload captures the error.
        assert "errors" in jira_project.last_jira_sync_counts
        assert any("synthetic Jira outage" in str(e) for e in jira_project.last_jira_sync_counts["errors"])


# ---------------------------------------------------------------------------
# 4. GET /api/projects/{id}/jira-tickets - search / sort / pagination
# ---------------------------------------------------------------------------


class TestJiraTicketsListEndpoint:
    def _seed(self, db_session, make_linked_ticket, jira_project):
        """Three linked tickets + their snapshots, freshly synced."""
        make_linked_ticket("POR-A", title="alpha task")
        make_linked_ticket("POR-B", title="bravo task")
        make_linked_ticket("POR-C", title="charlie task")
        fake = FakeReadOnlyJira({
            "POR-A": _make_jira_issue(
                "POR-A", status="In Progress", assignee="Alice", summary="Alpha jira title",
            ),
            "POR-B": _make_jira_issue(
                "POR-B", status="Done", assignee="Bob", summary="Bravo jira title",
            ),
            "POR-C": _make_jira_issue(
                "POR-C", status="In Review", assignee="Cara", summary="Charlie jira title",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

    def test_returns_all_linked_rows(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, make_linked_ticket, jira_project)
        r = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert len(body["rows"]) == 3
        # 10-column shape on every row.
        for row in body["rows"]:
            for k in (
                "ticket_id", "dwb_key", "dwb_sprint", "dwb_status",
                "title", "created_at", "updated_at",
                "jira_key", "jira_sprint", "jira_status", "jira_assignee",
                "jira_created_at", "jira_updated_at", "last_synced_at",
            ):
                assert k in row, f"missing key {k} in row: {row}"

    def test_fuzzy_search_matches_jira_assignee(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, make_linked_ticket, jira_project)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "Cara"},
        )
        body = r.json()
        assert body["total"] == 1
        assert body["rows"][0]["jira_assignee"] == "Cara"

    def test_fuzzy_search_matches_dwb_title(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, make_linked_ticket, jira_project)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "alpha"},
        )
        body = r.json()
        assert body["total"] == 1
        assert "alpha" in body["rows"][0]["title"].lower()

    def test_fuzzy_search_token_order_agnostic(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, make_linked_ticket, jira_project)
        # Two tokens, both must appear; order doesn't matter.
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "Done Bob"},
        )
        body = r.json()
        assert body["total"] == 1
        assert body["rows"][0]["jira_assignee"] == "Bob"
        assert body["rows"][0]["jira_status"] == "Done"

    def test_sort_by_jira_status_ascending(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, make_linked_ticket, jira_project)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"sort": "jira_status", "order": "asc"},
        )
        statuses = [row["jira_status"] for row in r.json()["rows"]]
        assert statuses == sorted(statuses)

    def test_sort_unknown_column_returns_400(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, make_linked_ticket, jira_project)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"sort": "anything_goes"},
        )
        assert r.status_code == 400

    def test_pagination(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed(db_session, make_linked_ticket, jira_project)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"limit": 2, "offset": 1, "sort": "dwb_key", "order": "asc"},
        )
        body = r.json()
        assert body["total"] == 3  # total is full count, not page count
        assert len(body["rows"]) == 2

    def test_unknown_project_returns_404(self, client):
        r = client.get("/api/projects/99999/jira-tickets")
        assert r.status_code == 404

    def test_non_jira_project_returns_empty_rows(
        self, client, make_project,
    ):
        """Non-Jira projects (jira_base_url null) should return 200 with
        zero rows - the table shows the empty state."""
        p = make_project()
        r = client.get(f"/api/projects/{p['id']}/jira-tickets")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["rows"] == []


# ---------------------------------------------------------------------------
# 5. POST /jira-sync + GET /jira-sync/status
# ---------------------------------------------------------------------------


class TestJiraSyncEndpoints:
    def test_sync_endpoint_400_when_no_jira_base_url(
        self, client, make_project,
    ):
        p = make_project()
        r = client.post(f"/api/projects/{p['id']}/jira-sync")
        assert r.status_code == 400
        assert "jira_base_url" in r.json()["detail"].lower()

    def test_sync_endpoint_404_when_missing_project(self, client):
        r = client.post("/api/projects/99999/jira-sync")
        assert r.status_code == 404

    def test_sync_endpoint_409_when_already_running(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        """Stamp running directly, then hit the endpoint - 409."""
        make_linked_ticket("POR-1")
        jira_project.last_jira_sync_status = JiraSyncStatus.running
        db_session.commit()
        r = client.post(f"/api/projects/{jira_project.id}/jira-sync")
        assert r.status_code == 409

    def test_sync_status_endpoint_shape(
        self, client, db_session, jira_project,
    ):
        r = client.get(f"/api/projects/{jira_project.id}/jira-sync/status")
        assert r.status_code == 200
        body = r.json()
        assert body["project_id"] == jira_project.id
        assert body["status"] == "idle"
        assert body["last_synced_at"] is None
        assert body["counts"] is None

    def test_sync_status_after_run_reflects_counts(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        """End-to-end: run a sync directly (with the fake client), then
        the status endpoint surfaces the persisted counts."""
        make_linked_ticket("POR-1")
        fake = FakeReadOnlyJira({"POR-1": _make_jira_issue("POR-1")})
        jira_sync.run_sync(
            db_session, jira_project.id, jira_client_override=fake,
        )

        r = client.get(f"/api/projects/{jira_project.id}/jira-sync/status")
        body = r.json()
        assert body["status"] == "done"
        assert body["last_synced_at"] is not None
        assert body["counts"]["added"] == 1
        assert body["counts"]["updated"] == 0
        assert body["counts"]["unchanged"] == 0
