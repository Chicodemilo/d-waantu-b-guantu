# Path: tests/test_single_active_invariant.py
# File: test_single_active_invariant.py
# Created: 2026-06-09
# Purpose: Tests for single-in_progress-epic + single-active-sprint per project (DWB-331)
# Caller: pytest
# Callees: app.routers.epics, app.routers.sprints, app.models.epic, app.models.sprint
# Data In: per-test db_session, factory fixtures
# Data Out: Assertions on 201/409 responses, transition behavior, multi-project isolation
# Last Modified: 2026-06-09

"""Verify the single-active invariants from DWB-331:

For epics (status=in_progress) and sprints (status=active):
- Happy path: first one through gets 201.
- Refusal: second one for the same project gets 409 with a friendly body
  surfacing the active row's id + name (so a caller can debug without a
  follow-up GET).
- Multi-project isolation: a project A active row does NOT block a
  project B active row.
- Transition frees the slot: moving the active row to a terminal status
  lets a new active row come in.

DB-level constraint is exercised through the API (which is the user-
facing contract); the service-layer pre-check produces a friendly 409
body, and the DB-level UNIQUE index is a backstop.
"""

import pytest


# ---------------------------------------------------------------------------
# Epic: single in_progress per project
# ---------------------------------------------------------------------------


class TestEpicSingleInProgress:
    def test_first_in_progress_epic_is_201(self, client, make_project):
        project = make_project()
        r = client.post(
            "/api/epics",
            json={
                "project_id": project["id"],
                "name": "First In-Progress",
                "status": "in_progress",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "in_progress"

    def test_second_in_progress_in_same_project_is_409(
        self, client, make_project
    ):
        project = make_project()
        first = client.post(
            "/api/epics",
            json={
                "project_id": project["id"],
                "name": "First",
                "status": "in_progress",
            },
        ).json()

        r = client.post(
            "/api/epics",
            json={
                "project_id": project["id"],
                "name": "Second",
                "status": "in_progress",
            },
        )
        assert r.status_code == 409, r.text
        body = r.json()
        # FastAPI wraps detail dict under "detail"
        detail = body.get("detail", body)
        assert detail["error"] == "another_in_progress_epic"
        assert detail["active_epic_id"] == first["id"]
        assert detail["active_epic_name"] == "First"

    def test_in_progress_in_different_project_is_201(
        self, client, make_project
    ):
        p1 = make_project()
        p2 = make_project()
        for pid in (p1["id"], p2["id"]):
            r = client.post(
                "/api/epics",
                json={
                    "project_id": pid,
                    "name": f"Epic for {pid}",
                    "status": "in_progress",
                },
            )
            assert r.status_code == 201, r.text

    def test_completing_in_progress_frees_the_slot(
        self, client, make_project
    ):
        project = make_project()
        first = client.post(
            "/api/epics",
            json={
                "project_id": project["id"],
                "name": "First",
                "status": "in_progress",
            },
        ).json()

        # Complete the first one.
        comp = client.patch(
            f"/api/epics/{first['id']}", json={"status": "completed"}
        )
        assert comp.status_code == 200

        # Now a new in_progress must land.
        r = client.post(
            "/api/epics",
            json={
                "project_id": project["id"],
                "name": "Second",
                "status": "in_progress",
            },
        )
        assert r.status_code == 201, r.text

    def test_patch_transition_blocked_when_another_in_progress(
        self, client, make_project
    ):
        """Existing open epic patching to in_progress is refused when another
        in_progress epic exists for the project."""
        project = make_project()
        client.post(
            "/api/epics",
            json={
                "project_id": project["id"],
                "name": "Already In-Progress",
                "status": "in_progress",
            },
        )
        other = client.post(
            "/api/epics",
            json={"project_id": project["id"], "name": "Open", "status": "open"},
        ).json()

        r = client.patch(
            f"/api/epics/{other['id']}", json={"status": "in_progress"}
        )
        assert r.status_code == 409
        detail = r.json().get("detail", {})
        assert detail.get("error") == "another_in_progress_epic"

    def test_patch_same_row_to_in_progress_is_noop_no_409(
        self, client, make_project
    ):
        """Re-PATCHing an already-in_progress epic to in_progress is a no-op
        and must NOT 409 against itself."""
        project = make_project()
        epic = client.post(
            "/api/epics",
            json={
                "project_id": project["id"],
                "name": "Self",
                "status": "in_progress",
            },
        ).json()

        r = client.patch(
            f"/api/epics/{epic['id']}", json={"status": "in_progress"}
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Sprint: single active per project
# ---------------------------------------------------------------------------


class TestSprintSingleActive:
    def test_first_active_sprint_is_201(self, client, make_epic):
        epic = make_epic()
        r = client.post(
            "/api/sprints",
            json={
                "project_id": epic["project_id"],
                "epic_id": epic["id"],
                "sprint_number": 1,
                "status": "active",
                "goal": "Inaugural sprint",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "active"

    def test_second_active_sprint_in_same_project_is_409(
        self, client, make_epic
    ):
        epic = make_epic()
        first = client.post(
            "/api/sprints",
            json={
                "project_id": epic["project_id"],
                "epic_id": epic["id"],
                "sprint_number": 1,
                "status": "active",
                "goal": "First",
            },
        ).json()

        r = client.post(
            "/api/sprints",
            json={
                "project_id": epic["project_id"],
                "epic_id": epic["id"],
                "sprint_number": 2,
                "status": "active",
                "goal": "Second",
            },
        )
        assert r.status_code == 409, r.text
        detail = r.json().get("detail", {})
        assert detail["error"] == "another_active_sprint"
        assert detail["active_sprint_id"] == first["id"]
        assert detail["active_sprint_number"] == 1

    def test_active_in_different_project_is_201(self, client, make_epic):
        e1 = make_epic()
        e2 = make_epic()
        for ep in (e1, e2):
            r = client.post(
                "/api/sprints",
                json={
                    "project_id": ep["project_id"],
                    "epic_id": ep["id"],
                    "sprint_number": 1,
                    "status": "active",
                    "goal": f"Sprint for project {ep['project_id']}",
                },
            )
            assert r.status_code == 201, r.text

    def test_planned_then_patch_to_active_blocked_when_another_active(
        self, client, make_epic
    ):
        """Existing planned sprint patching to active is refused when another
        active sprint exists for the project."""
        epic = make_epic()
        client.post(
            "/api/sprints",
            json={
                "project_id": epic["project_id"],
                "epic_id": epic["id"],
                "sprint_number": 1,
                "status": "active",
                "goal": "First",
            },
        )
        planned = client.post(
            "/api/sprints",
            json={
                "project_id": epic["project_id"],
                "epic_id": epic["id"],
                "sprint_number": 2,
                "status": "planned",
                "goal": "Next",
            },
        ).json()

        r = client.patch(
            f"/api/sprints/{planned['id']}", json={"status": "active"}
        )
        assert r.status_code == 409
        detail = r.json().get("detail", {})
        assert detail.get("error") == "another_active_sprint"

    def test_patch_same_row_active_to_active_is_noop_no_409(
        self, client, make_epic
    ):
        """Re-PATCHing an already-active sprint to active is a no-op and must
        NOT 409 against itself."""
        epic = make_epic()
        sprint = client.post(
            "/api/sprints",
            json={
                "project_id": epic["project_id"],
                "epic_id": epic["id"],
                "sprint_number": 1,
                "status": "active",
                "goal": "Self",
            },
        ).json()

        r = client.patch(
            f"/api/sprints/{sprint['id']}", json={"status": "active"}
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# DB-level UNIQUE backstop
# ---------------------------------------------------------------------------


class TestDbLevelConstraintBackstop:
    """The service-layer 409 is the friendly path; the (project_id, is_*)
    UNIQUE index is the backstop. Insert two rows that bypass the service
    via the ORM and assert the DB refuses the second."""

    def test_db_refuses_second_in_progress_epic(
        self, db_session, make_project
    ):
        from sqlalchemy.exc import IntegrityError

        from app.models.epic import Epic, EpicStatus

        project = make_project()
        a = Epic(
            project_id=project["id"],
            name="A",
            status=EpicStatus.in_progress,
        )
        b = Epic(
            project_id=project["id"],
            name="B",
            status=EpicStatus.in_progress,
        )
        db_session.add_all([a, b])
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_db_refuses_second_active_sprint(
        self, db_session, make_project, make_epic
    ):
        from sqlalchemy.exc import IntegrityError

        from app.models.sprint import Sprint, SprintStatus

        project = make_project()
        epic = make_epic(project_id=project["id"])
        a = Sprint(
            project_id=project["id"],
            epic_id=epic["id"],
            name="A",
            sprint_number=1,
            status=SprintStatus.active,
        )
        b = Sprint(
            project_id=project["id"],
            epic_id=epic["id"],
            name="B",
            sprint_number=2,
            status=SprintStatus.active,
        )
        db_session.add_all([a, b])
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()
