# Path: tests/test_jira_parent_dwb364.py
# File: test_jira_parent_dwb364.py
# Created: 2026-06-10
# Purpose: Tests for DWB-364 - Parent column (subtasks only) end-to-end
# Caller: pytest
# Callees: app.services.jira._normalize_issue, app.services.jira_sync.run_sync,
#          GET /api/projects/{id}/jira-tickets, app.models.jira_ticket_snapshot.JiraTicketSnapshot
# Data In: synthetic Jira-linked project, FakeReadOnlyJira with subtask + non-subtask issue payloads
# Data Out: Assertions on issue_type_is_subtask normalizer surface, snapshot column write gating,
#           NULL on non-subtasks, list endpoint shape, search + sort whitelist coverage.
# Last Modified: 2026-06-10

"""DWB-364 coverage.

The unified Jira table gains a Parent column populated ONLY for
subtasks. The gating signal is Jira's authoritative
``issuetype.subtask`` boolean (probed 2026-06-10 against POR-5840 to
confirm the field shape); the spec's mention of "Sub-task" by name is
fragile across instance naming variants ("Subtask", "Sub-task",
custom subtask-like types). Tying the gate to the boolean rather than
the name string keeps the column robust.

Pinned behaviors:

  1. _normalize_issue surfaces ``issue_type_is_subtask`` (bool) from
     issue.fields.issuetype.subtask, defaulting False when missing.
  2. jira_sync persists ``jira_parent_key`` from parent.key BUT ONLY
     when the issue is a subtask; non-subtask rows write NULL even
     when the source payload has a parent (e.g. Story->Epic linkage).
  3. The list endpoint serves the new column on every row.
  4. Search hits jira_parent_key (substring match like the other
     columns).
  5. Sort whitelist exposes jira_parent_key (subtasks cluster
     together when sorted).
  6. Pre-DWB-364 snapshot rows (NULL on jira_parent_key) flow through
     the list endpoint cleanly.
"""

import pytest

from app.services import jira as jira_service
from app.services import jira_sync


# Re-use the read-only Jira fake from the DWB-342/356/362/363 suites.
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


def _normalized_issue(key, *, parent_key=None, parent_type=None,
                       issue_type="Task", is_subtask=False, summary=None):
    """Normalized-shape issue (post _normalize_issue) for the sync's
    mocked batch_get_issues. Mirrors the keys jira_sync._normalize_jira_payload
    reads, including the DWB-364 issue_type_is_subtask boolean."""
    return {
        "key": key,
        "id": "id-" + key,
        "summary": summary or f"summary of {key}",
        "status": "In Progress",
        "status_category": "In Progress",
        "assignee": "Alice",
        "reporter": "Bob",
        "issue_type": issue_type,
        "issue_type_is_subtask": is_subtask,
        "parent_key": parent_key,
        "parent_type": parent_type,
        "priority": "Medium",
        "created": "2026-05-01T12:00:00.000+0000",
        "updated": "2026-06-01T12:00:00.000+0000",
        "sprint_name": None,
        # DWB-363 epic_key: parent-as-Epic only. A subtask's parent is
        # typically a Story so epic_key resolves elsewhere; here we just
        # mirror parent_key into epic_key when parent_type=="Epic" so
        # the sync's epic-name lookup is deterministic in tests.
        "epic_key": parent_key if parent_type == "Epic" else None,
    }


# ---------------------------------------------------------------------------
# 1. Normalizer surfaces issue_type_is_subtask boolean
# ---------------------------------------------------------------------------


class TestNormalizerSurfacesSubtaskBoolean:
    def test_subtask_issuetype_sets_is_subtask_true(self):
        raw = {
            "key": "POR-1", "id": "1",
            "fields": {
                "summary": "x",
                "issuetype": {"name": "Subtask", "subtask": True},
                "parent": {
                    "key": "POR-99",
                    "fields": {"issuetype": {"name": "Story"}},
                },
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["issue_type_is_subtask"] is True
        assert out["parent_key"] == "POR-99"

    def test_task_issuetype_sets_is_subtask_false(self):
        raw = {
            "key": "POR-2", "id": "2",
            "fields": {
                "summary": "x",
                "issuetype": {"name": "Task", "subtask": False},
                "parent": {
                    "key": "POR-100",
                    "fields": {"issuetype": {"name": "Epic"}},
                },
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["issue_type_is_subtask"] is False
        # parent_key still surfaces on non-subtasks; the snapshot column
        # gating happens at sync time, not in the normalizer.
        assert out["parent_key"] == "POR-100"

    def test_missing_subtask_field_defaults_false(self):
        """Defensive: a legacy/abnormal payload that omits the subtask
        boolean should default the surface key to False, not crash."""
        raw = {
            "key": "POR-3", "id": "3",
            "fields": {
                "summary": "x",
                "issuetype": {"name": "Unknown"},
            },
        }
        out = jira_service._normalize_issue(raw)
        assert out["issue_type_is_subtask"] is False


# ---------------------------------------------------------------------------
# 2. Sync gating: parent_key persisted only for subtasks
# ---------------------------------------------------------------------------


@pytest.fixture
def jira_project(db_session):
    from app.models.project import Project
    p = Project(
        prefix="J364",
        name="DWB-364 Test",
        jira_base_url="https://example.atlassian.net",
        jira_project_key="POR",
        repo_path="/tmp/j364",
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
    counter = [500]

    def _make(jira_key, title="row"):
        counter[0] += 1
        t = Ticket(
            project_id=jira_project.id, epic_id=epic.id, sprint_id=sprint.id,
            ticket_number=counter[0], ticket_key=f"J364-{counter[0]}",
            title=title, status=TicketStatus.in_progress,
            jira_issue_key=jira_key,
        )
        db_session.add(t)
        db_session.flush()
        return t

    return _make


class TestSyncGatesParentKeyToSubtasks:
    def test_subtask_persists_parent_key(
        self, db_session, jira_project, make_linked_ticket,
    ):
        from app.models.jira_ticket_snapshot import JiraTicketSnapshot

        make_linked_ticket("POR-SUB")
        fake = _FakeReadOnlyJira({
            "POR-SUB": _normalized_issue(
                "POR-SUB", parent_key="POR-STORY", parent_type="Story",
                issue_type="Subtask", is_subtask=True,
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-SUB",
        ).one()
        assert snap.jira_parent_key == "POR-STORY"

    def test_task_with_epic_parent_does_not_persist_parent_key(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """A Task whose parent is an Epic has parent_key set on the
        normalized payload (used by DWB-363 for epic resolution), but
        the snapshot's jira_parent_key stays NULL because this isn't a
        subtask. The Parent column is subtask-exclusive."""
        from app.models.jira_ticket_snapshot import JiraTicketSnapshot

        make_linked_ticket("POR-TASK")
        fake = _FakeReadOnlyJira({
            "POR-TASK": _normalized_issue(
                "POR-TASK", parent_key="POR-EPIC", parent_type="Epic",
                issue_type="Task", is_subtask=False,
            ),
            # Epic for DWB-363 batched name resolver.
            "POR-EPIC": _normalized_issue(
                "POR-EPIC", issue_type="Epic", is_subtask=False,
                summary="Epic Summary",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-TASK",
        ).one()
        assert snap.jira_parent_key is None
        # Sanity: DWB-363 epic column still populates for this row.
        assert snap.jira_epic_key == "POR-EPIC"

    def test_standalone_task_persists_null_parent_key(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """Top-level task with no parent at all - NULL parent_key."""
        from app.models.jira_ticket_snapshot import JiraTicketSnapshot

        make_linked_ticket("POR-STANDALONE")
        fake = _FakeReadOnlyJira({
            "POR-STANDALONE": _normalized_issue(
                "POR-STANDALONE", parent_key=None, parent_type=None,
                issue_type="Task", is_subtask=False,
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        snap = db_session.query(JiraTicketSnapshot).filter_by(
            jira_issue_key="POR-STANDALONE",
        ).one()
        assert snap.jira_parent_key is None

    def test_mixed_seed_only_subtasks_have_parent_key(
        self, db_session, jira_project, make_linked_ticket,
    ):
        """End-to-end: seed 3 subtasks + 3 non-subtasks. After sync,
        exactly 3 rows have jira_parent_key set."""
        from app.models.jira_ticket_snapshot import JiraTicketSnapshot

        for i in range(3):
            make_linked_ticket(f"POR-SUB{i}")
            make_linked_ticket(f"POR-TASK{i}")
        fake = _FakeReadOnlyJira({
            **{
                f"POR-SUB{i}": _normalized_issue(
                    f"POR-SUB{i}", parent_key=f"POR-STORY{i}",
                    parent_type="Story", issue_type="Subtask", is_subtask=True,
                )
                for i in range(3)
            },
            **{
                f"POR-TASK{i}": _normalized_issue(
                    f"POR-TASK{i}", parent_key="POR-EPIC",
                    parent_type="Epic", issue_type="Task", is_subtask=False,
                )
                for i in range(3)
            },
            "POR-EPIC": _normalized_issue(
                "POR-EPIC", issue_type="Epic", is_subtask=False, summary="E",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        with_parent = db_session.query(JiraTicketSnapshot).filter(
            JiraTicketSnapshot.jira_parent_key.isnot(None),
        ).all()
        without_parent = db_session.query(JiraTicketSnapshot).filter(
            JiraTicketSnapshot.jira_parent_key.is_(None),
        ).all()
        assert len(with_parent) == 3
        assert len(without_parent) == 3
        # And the with-parent rows are exactly the subtasks.
        sub_keys = {s.jira_issue_key for s in with_parent}
        assert sub_keys == {"POR-SUB0", "POR-SUB1", "POR-SUB2"}


# ---------------------------------------------------------------------------
# 3. List endpoint surfaces the column + handles NULL cleanly
# ---------------------------------------------------------------------------


class TestListEndpointServesParentKey:
    def test_subtask_row_carries_parent_key_through_endpoint(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        make_linked_ticket("POR-S1")
        make_linked_ticket("POR-T1")
        fake = _FakeReadOnlyJira({
            "POR-S1": _normalized_issue(
                "POR-S1", parent_key="POR-PA", parent_type="Story",
                issue_type="Subtask", is_subtask=True,
            ),
            "POR-T1": _normalized_issue(
                "POR-T1", parent_key=None, parent_type=None,
                issue_type="Task", is_subtask=False,
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        r = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        assert r.status_code == 200, r.text
        rows = {row["jira_key"]: row for row in r.json()["rows"]}
        assert "jira_parent_key" in rows["POR-S1"]
        assert rows["POR-S1"]["jira_parent_key"] == "POR-PA"
        assert rows["POR-T1"]["jira_parent_key"] is None

    def test_pre_dwb364_snapshot_serves_null(
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
            # jira_parent_key intentionally omitted.
        )
        db_session.add(snap)
        db_session.flush()

        r = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        match = next(row for row in r.json()["rows"] if row["jira_key"] == "POR-OLD")
        assert match["jira_parent_key"] is None


# ---------------------------------------------------------------------------
# 4. Search + sort
# ---------------------------------------------------------------------------


class TestSearchAndSortOnParentKey:
    def _seed_three(self, db_session, jira_project, make_linked_ticket):
        make_linked_ticket("POR-A")
        make_linked_ticket("POR-B")
        make_linked_ticket("POR-C")
        fake = _FakeReadOnlyJira({
            "POR-A": _normalized_issue(
                "POR-A", parent_key="POR-STORY-100",
                parent_type="Story", issue_type="Subtask", is_subtask=True,
            ),
            "POR-B": _normalized_issue(
                "POR-B", parent_key="POR-STORY-200",
                parent_type="Story", issue_type="Subtask", is_subtask=True,
            ),
            "POR-C": _normalized_issue(
                "POR-C", parent_key=None, parent_type=None,
                issue_type="Task", is_subtask=False,
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

    def test_search_by_parent_key_substring(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed_three(db_session, jira_project, make_linked_ticket)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"q": "STORY-200"},
        )
        body = r.json()
        assert body["total"] == 1
        assert body["rows"][0]["jira_key"] == "POR-B"
        assert body["rows"][0]["jira_parent_key"] == "POR-STORY-200"

    def test_sort_asc_by_parent_key_clusters_subtasks(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        self._seed_three(db_session, jira_project, make_linked_ticket)
        r = client.get(
            f"/api/projects/{jira_project.id}/jira-tickets",
            params={"sort": "jira_parent_key", "order": "asc"},
        )
        keys = [row["jira_parent_key"] for row in r.json()["rows"]]
        # MySQL NULLs first when ascending (vs Postgres which defaults
        # to NULLs last). Either way: the two subtasks should appear in
        # ascending parent-key order somewhere in the result.
        non_null = [k for k in keys if k is not None]
        assert non_null == sorted(non_null)
        assert non_null == ["POR-STORY-100", "POR-STORY-200"]
