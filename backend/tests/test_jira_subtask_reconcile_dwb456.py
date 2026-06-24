# Path: tests/test_jira_subtask_reconcile_dwb456.py
# File: test_jira_subtask_reconcile_dwb456.py
# Created: 2026-06-24
# Purpose: Tests for DWB-456 - Jira sub-task reconcile (type mapping + parent resolution), READ-ONLY toward Jira
# Caller: pytest
# Callees: app.services.jira_sync.run_sync
# Data In: synthetic Jira-linked project, FakeReadOnlyJira with subtask + parent issue payloads
# Data Out: Assertions on DWB ticket.ticket_type + parent_ticket_id, unresolved-parent error path, read-only invariant
# Last Modified: 2026-06-24

"""DWB-456 coverage.

After the snapshot refresh, jira_sync reconciles DWB-side sub-task linkage:
  - a linked ticket whose Jira issue type is a sub-task gets ticket_type=subtask;
  - its jira_parent_key resolves to the parent DWB ticket (via jira_issue_key)
    and sets parent_ticket_id;
  - if the parent isn't linked in DWB, parent_ticket_id stays null and a note
    is appended to counts["errors"] (no silent drop).

The reconcile must NOT call Jira (read-only contract). The FakeReadOnlyJira
seam raises AttributeError on any non-read method, so a stray write would
fail loudly.
"""

import pytest

from app.models.ticket import TicketType
from app.services import jira_sync


_READ_METHODS = frozenset({
    "batch_get_issues", "get_issue", "list_projects", "search_issues",
    "get_active_sprints", "get_sprint_issues",
})


class FakeReadOnlyJira:
    """Read-only injection seam; mirrors test_jira_sync_dwb342.FakeReadOnlyJira."""

    def __init__(self, issues_by_key: dict):
        self._issues_by_key = issues_by_key
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        if name not in _READ_METHODS:
            raise AttributeError(
                f"FakeReadOnlyJira refuses access to '{name}' - read-only contract."
            )

        def _stub(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "batch_get_issues":
                keys = args[0] if args else kwargs.get("issue_keys", [])
                return [self._issues_by_key[k] for k in keys if k in self._issues_by_key]
            return []

        return _stub


def _make_issue(
    key: str,
    *,
    issue_type: str = "Story",
    is_subtask: bool = False,
    parent_key: str | None = None,
    summary: str = "issue",
):
    """Normalized issue dict matching app.services.jira._normalize_issue shape."""
    return {
        "key": key,
        "id": "id-" + key,
        "summary": summary,
        "status": "In Progress",
        "assignee": "Alice",
        "reporter": "Bob",
        "description": None,
        "issue_type": issue_type,
        "issue_type_is_subtask": is_subtask,
        "parent_key": parent_key,
        "parent_type": None,
        "epic_key": None,
        "priority": "Medium",
        "created": "2026-05-01T12:00:00.000+0000",
        "updated": "2026-06-01T12:00:00.000+0000",
        "sprint_name": None,
    }


@pytest.fixture
def jira_project(db_session):
    from app.models.project import Project

    p = Project(
        prefix="JSUB",
        name="Synthetic Jira Subtask Project",
        jira_base_url="https://example.atlassian.net",
        jira_project_key="POR",
        repo_path="/tmp/jsub",
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def make_linked_ticket(db_session, jira_project):
    from app.models.epic import Epic, EpicStatus
    from app.models.sprint import Sprint, SprintStatus
    from app.models.ticket import Ticket, TicketStatus

    epic = Epic(project_id=jira_project.id, name="Epic", status=EpicStatus.open)
    db_session.add(epic)
    db_session.flush()
    sprint = Sprint(
        project_id=jira_project.id, epic_id=epic.id, name="S1",
        sprint_number=1, status=SprintStatus.active,
    )
    db_session.add(sprint)
    db_session.flush()

    _counter = [200]

    def _make(jira_key: str, title: str = "synthetic"):
        _counter[0] += 1
        t = Ticket(
            project_id=jira_project.id,
            epic_id=epic.id,
            sprint_id=sprint.id,
            ticket_number=_counter[0],
            ticket_key=f"JSUB-{_counter[0]}",
            title=title,
            status=TicketStatus.in_progress,
            jira_issue_key=jira_key,
        )
        db_session.add(t)
        db_session.flush()
        return t

    return _make


class TestSubtaskReconcile:
    def test_subtask_type_mapping(self, db_session, jira_project, make_linked_ticket):
        """A linked ticket whose Jira type is Sub-task becomes ticket_type=subtask."""
        parent = make_linked_ticket("POR-100", title="parent")
        child = make_linked_ticket("POR-101", title="child")

        fake = FakeReadOnlyJira({
            "POR-100": _make_issue("POR-100", issue_type="Task"),
            "POR-101": _make_issue(
                "POR-101", issue_type="Sub-task", is_subtask=True, parent_key="POR-100",
            ),
        })
        counts = jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        db_session.refresh(child)
        db_session.refresh(parent)
        assert child.ticket_type == TicketType.subtask
        # parent stays whatever it was (a regular task), not flipped to subtask
        assert parent.ticket_type != TicketType.subtask
        assert counts["errors"] == []

    def test_parent_resolution(self, db_session, jira_project, make_linked_ticket):
        """jira_parent_key resolves to the parent DWB ticket -> parent_ticket_id set."""
        parent = make_linked_ticket("POR-200", title="parent")
        child = make_linked_ticket("POR-201", title="child")

        fake = FakeReadOnlyJira({
            "POR-200": _make_issue("POR-200", issue_type="Task"),
            "POR-201": _make_issue(
                "POR-201", issue_type="Sub-task", is_subtask=True, parent_key="POR-200",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        db_session.refresh(child)
        assert child.parent_ticket_id == parent.id

    def test_subtask_type_variant_subtask_no_hyphen(self, db_session, jira_project, make_linked_ticket):
        """The 'Subtask' (no hyphen) label is also recognised."""
        parent = make_linked_ticket("POR-300", title="parent")
        child = make_linked_ticket("POR-301", title="child")

        fake = FakeReadOnlyJira({
            "POR-300": _make_issue("POR-300", issue_type="Task"),
            "POR-301": _make_issue(
                "POR-301", issue_type="Subtask", is_subtask=True, parent_key="POR-300",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        db_session.refresh(child)
        assert child.ticket_type == TicketType.subtask
        assert child.parent_ticket_id == parent.id

    def test_unresolved_parent_error_path(self, db_session, jira_project, make_linked_ticket):
        """A sub-task whose parent isn't linked in DWB leaves parent_ticket_id
        null and appends a note to counts['errors'] (no silent drop)."""
        child = make_linked_ticket("POR-401", title="orphan child")

        fake = FakeReadOnlyJira({
            # POR-400 (the Jira parent) is NOT linked in DWB.
            "POR-401": _make_issue(
                "POR-401", issue_type="Sub-task", is_subtask=True, parent_key="POR-400",
            ),
        })
        counts = jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        db_session.refresh(child)
        assert child.ticket_type == TicketType.subtask  # still mapped
        assert child.parent_ticket_id is None  # but unlinked
        # error note present and references the unresolved parent key
        unresolved = [
            e for e in counts["errors"]
            if isinstance(e, dict) and "subtask_parent_unresolved" in e
        ]
        assert len(unresolved) == 1
        assert "POR-400" in unresolved[0]["subtask_parent_unresolved"]

    def test_non_subtask_unaffected(self, db_session, jira_project, make_linked_ticket):
        """Regular issue types are not reclassified and get no parent link."""
        t = make_linked_ticket("POR-500", title="plain story")

        fake = FakeReadOnlyJira({"POR-500": _make_issue("POR-500", issue_type="Story")})
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        db_session.refresh(t)
        assert t.ticket_type != TicketType.subtask
        assert t.parent_ticket_id is None

    def test_jira_tickets_endpoint_exposes_dwb_parent_key(
        self, client, db_session, jira_project, make_linked_ticket,
    ):
        """The GET /jira-tickets row carries dwb_parent_key resolved server-
        side from parent_ticket_id -> parent ticket_key (pagination-safe)."""
        parent = make_linked_ticket("POR-700", title="parent")
        child = make_linked_ticket("POR-701", title="child")
        fake = FakeReadOnlyJira({
            "POR-700": _make_issue("POR-700", issue_type="Task"),
            "POR-701": _make_issue(
                "POR-701", issue_type="Sub-task", is_subtask=True, parent_key="POR-700",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)
        db_session.flush()

        resp = client.get(f"/api/projects/{jira_project.id}/jira-tickets")
        assert resp.status_code == 200
        rows = {r["jira_key"]: r for r in resp.json()["rows"]}
        # every row carries the key
        assert "dwb_parent_key" in rows["POR-701"]
        # child resolves to the parent's DWB ticket_key
        assert rows["POR-701"]["dwb_parent_key"] == parent.ticket_key
        # parent (no DWB parent) serves null
        assert rows["POR-700"]["dwb_parent_key"] is None

    def test_reconcile_makes_no_jira_write_calls(self, db_session, jira_project, make_linked_ticket):
        """Read-only invariant: only batch_get_issues is ever called."""
        make_linked_ticket("POR-600", title="parent")
        make_linked_ticket("POR-601", title="child")
        fake = FakeReadOnlyJira({
            "POR-600": _make_issue("POR-600", issue_type="Task"),
            "POR-601": _make_issue(
                "POR-601", issue_type="Sub-task", is_subtask=True, parent_key="POR-600",
            ),
        })
        jira_sync.run_sync(db_session, jira_project.id, jira_client_override=fake)

        called_methods = {c[0] for c in fake.calls}
        assert called_methods <= {"batch_get_issues"}
