# Path:          tests/test_subtasks.py
# File:          test_subtasks.py
# Created:       2026-06-24
# Purpose:       Validation + inheritance tests for native sub-tasks (DWB-455)
# Caller:        pytest
# Callees:       POST/PATCH/GET /api/tickets
# Data In:       Factory-created projects, sprints, epics, tickets via conftest fixtures
# Data Out:      Assertions on HTTP status codes, parent linkage, epic/sprint inheritance, embedded subtasks
# Last Modified: 2026-06-24

"""Tests for native sub-task support (DWB-455).

Rules under test:
  - ticket_type=subtask REQUIRES parent_ticket_id; non-subtask types must
    leave it null.
  - parent must be in the same project.
  - parent cannot itself be a subtask (one level only).
  - subtask inherits epic_id from parent; defaults sprint_id to the parent's
    sprint when omitted.
  - converting a ticket that already has children into a subtask is blocked.
  - TicketRead embeds a subtasks list of child summaries.
"""

import pytest


def _create(client, **body):
    return client.post("/api/tickets", json=body)


class TestSubtaskCreateValidation:
    def test_subtask_without_parent_rejected(self, client, make_ticket):
        parent = make_ticket()
        r = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9001,
            ticket_key="SUB-9001",
            title="orphan subtask",
            ticket_type="subtask",
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "subtask_requires_parent"

    def test_non_subtask_with_parent_rejected(self, client, make_ticket):
        parent = make_ticket()
        r = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9002,
            ticket_key="SUB-9002",
            title="task with parent",
            ticket_type="task",
            parent_ticket_id=parent["id"],
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "parent_only_on_subtask"

    def test_parent_not_found_rejected(self, client, make_ticket):
        parent = make_ticket()  # establishes a project with an active sprint
        r = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9003,
            ticket_key="SUB-9003",
            title="bad parent",
            ticket_type="subtask",
            parent_ticket_id=999999,
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "parent_not_found"

    def test_parent_cross_project_rejected(self, client, make_ticket):
        parent = make_ticket()
        other = make_ticket()  # different project
        r = _create(
            client,
            project_id=other["project_id"],
            ticket_number=9004,
            ticket_key="SUB-9004",
            title="cross-project subtask",
            ticket_type="subtask",
            parent_ticket_id=parent["id"],
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "parent_cross_project"

    def test_parent_cannot_be_subtask(self, client, make_ticket):
        parent = make_ticket()
        # First-level subtask
        sub = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9005,
            ticket_key="SUB-9005",
            title="level one",
            ticket_type="subtask",
            parent_ticket_id=parent["id"],
        ).json()
        # Attempt a subtask OF the subtask -> rejected (one level only)
        r = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9006,
            ticket_key="SUB-9006",
            title="level two",
            ticket_type="subtask",
            parent_ticket_id=sub["id"],
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "parent_is_subtask"


class TestSubtaskInheritance:
    def test_subtask_inherits_epic_and_sprint(self, client, make_ticket):
        parent = make_ticket()
        r = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9010,
            ticket_key="SUB-9010",
            title="inherit",
            ticket_type="subtask",
            parent_ticket_id=parent["id"],
        )
        assert r.status_code == 201
        child = r.json()
        assert child["parent_ticket_id"] == parent["id"]
        assert child["epic_id"] == parent["epic_id"]
        # sprint defaults to the parent's sprint when omitted
        assert child["sprint_id"] == parent["sprint_id"]

    def test_subtask_epic_inherits_even_when_supplied(self, client, make_ticket, make_epic):
        parent = make_ticket()
        # supply a different epic; subtask must still inherit the parent's
        other_epic = make_epic(project_id=parent["project_id"])
        r = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9011,
            ticket_key="SUB-9011",
            title="epic override",
            ticket_type="subtask",
            parent_ticket_id=parent["id"],
            epic_id=other_epic["id"],
        )
        assert r.status_code == 201
        assert r.json()["epic_id"] == parent["epic_id"]


class TestSubtaskEmbedAndUpdate:
    def test_parent_read_embeds_subtasks(self, client, make_ticket):
        parent = make_ticket()
        sub = _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9020,
            ticket_key="SUB-9020",
            title="child",
            ticket_type="subtask",
            parent_ticket_id=parent["id"],
        ).json()
        data = client.get(f"/api/tickets/{parent['id']}").json()
        sub_ids = [s["id"] for s in data["subtasks"]]
        assert sub["id"] in sub_ids
        # the subtask itself has no children
        child_data = client.get(f"/api/tickets/{sub['id']}").json()
        assert child_data["subtasks"] == []

    def test_convert_task_to_subtask_via_patch(self, client, make_ticket):
        parent = make_ticket()
        child = make_ticket(project_id=parent["project_id"])
        r = client.patch(
            f"/api/tickets/{child['id']}",
            json={"ticket_type": "subtask", "parent_ticket_id": parent["id"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ticket_type"] == "subtask"
        assert body["parent_ticket_id"] == parent["id"]
        assert body["epic_id"] == parent["epic_id"]

    def test_cannot_convert_ticket_with_children_into_subtask(self, client, make_ticket):
        parent = make_ticket()
        grandparent = make_ticket(project_id=parent["project_id"])
        # Give `parent` a child so it now has subtasks.
        _create(
            client,
            project_id=parent["project_id"],
            ticket_number=9030,
            ticket_key="SUB-9030",
            title="a child",
            ticket_type="subtask",
            parent_ticket_id=parent["id"],
        )
        # Now try to make `parent` itself a subtask of grandparent -> blocked.
        r = client.patch(
            f"/api/tickets/{parent['id']}",
            json={"ticket_type": "subtask", "parent_ticket_id": grandparent["id"]},
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "has_children_cannot_be_subtask"

    def test_patch_subtask_without_parent_rejected(self, client, make_ticket):
        t = make_ticket()
        r = client.patch(
            f"/api/tickets/{t['id']}",
            json={"ticket_type": "subtask"},
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "subtask_requires_parent"
