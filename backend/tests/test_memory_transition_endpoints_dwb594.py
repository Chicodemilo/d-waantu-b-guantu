# Path: tests/test_memory_transition_endpoints_dwb594.py
# File: test_memory_transition_endpoints_dwb594.py
# Created: 2026-09-30 (DWB-594)
# Purpose: Guard the adopt pipeline's HTTP surface - the dry run writes nothing,
#          no route hands over every candidate, and the decide loop works end to
#          end through the API.
# Caller: pytest
# Callees: /api/projects/{id}/memory-transition/*, /api/memory-transitions/*
# Data In: lat_test rows plus memory.md files under tmp_path
# Data Out: assertions
# Last Modified: 2026-09-30 (DWB-594)

"""DWB-594 at the HTTP layer.

The structural test is the one that matters: no route returns every candidate.
`/plan` is the single exception and it writes nothing, creates no run and exists
for a human deciding whether to begin. A `GET /entries` added later for
convenience would defeat the ticket, and it would look like an improvement.
"""

from pathlib import Path

import pytest

from app.models.memory_transition import MemoryTransition, TransitionState
from app.models.project import MemoryMode

FILE = (
    "## Verification\n"
    "- a green run and a recorded run differ\n"
    "- never live-test a write path\n"
)


def _write(tmp_path, prefix, name, text=FILE):
    d = Path(tmp_path) / ".dwb" / "memory" / prefix / name
    d.mkdir(parents=True, exist_ok=True)
    path = d / "memory.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project_with_memory(client, make_project, make_agent, tmp_path):
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"], name="Adoptee")
    path = _write(tmp_path, project["prefix"], "Adoptee")
    return project, agent, path


@pytest.fixture
def adopting(client, project_with_memory):
    """Started through the real PATCH, so the whole seam is exercised."""
    project, agent, path = project_with_memory
    r = client.patch(
        f"/api/projects/{project['id']}",
        json={"memory_mode": "adopting", "memory_mode_confirmed": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["memory_mode"] == "adopting"
    return project, agent, path


class TestTheDryRunWritesNothing:
    """DWB-594 acceptance 5."""

    def test_the_plan_lists_candidates_without_persisting(
        self, client, db_session, project_with_memory
    ):
        project, _agent, _path = project_with_memory
        before = db_session.query(MemoryTransition).count()

        r = client.get(f"/api/projects/{project['id']}/memory-transition/plan")
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["candidate_count"] == 2
        assert len(body["candidates"]) == 2
        assert db_session.query(MemoryTransition).count() == before

    def test_the_plan_is_available_before_the_transition_starts(
        self, client, project_with_memory
    ):
        """The moment the answer is actionable. A plan you can only see after
        committing to the work answers the question too late."""
        project, _agent, _path = project_with_memory
        assert project["memory_mode"] == "stock"
        r = client.get(f"/api/projects/{project['id']}/memory-transition/plan")
        assert r.status_code == 200
        assert r.json()["candidate_count"] == 2

    def test_the_plan_creates_no_run(self, client, db_session, project_with_memory):
        from app.models.memory_transition import MemoryTransitionRun

        project, _agent, _path = project_with_memory
        before = db_session.query(MemoryTransitionRun).count()
        client.get(f"/api/projects/{project['id']}/memory-transition/plan")
        assert db_session.query(MemoryTransitionRun).count() == before

    def test_the_plan_leaves_the_file_byte_identical(
        self, client, project_with_memory
    ):
        project, _agent, path = project_with_memory
        before = path.read_bytes()
        client.get(f"/api/projects/{project['id']}/memory-transition/plan")
        assert path.read_bytes() == before

    def test_the_plan_carries_no_proposed_tier(self, client, project_with_memory):
        """Section 4: the snapshot makes no judgement. An agent shown a proposed
        answer agrees with it, which is the rubber-stamp the design prevents."""
        project, _agent, _path = project_with_memory
        body = client.get(
            f"/api/projects/{project['id']}/memory-transition/plan"
        ).json()
        for candidate in body["candidates"]:
            assert "proposed_tier" not in candidate
            assert "tier" not in candidate

    def test_the_plan_surfaces_a_would_refuse(
        self, client, make_project, make_agent, tmp_path
    ):
        """An unreadable file makes the start refuse, and the plan says so
        BEFORE anyone commits to the work."""
        import os

        project = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project["id"], name="Locked")
        path = _write(tmp_path, project["prefix"], "Locked")
        os.chmod(path, 0o000)
        try:
            if os.geteuid() == 0:  # pragma: no cover
                pytest.skip("running as root")
            body = client.get(
                f"/api/projects/{project['id']}/memory-transition/plan"
            ).json()
        finally:
            os.chmod(path, 0o644)
        assert body["would_refuse"] is True
        assert body["unreadable"]


class TestNoRouteHandsOverTheQueue:
    def test_next_returns_one_entry_and_a_count(self, client, adopting):
        project, agent, _path = adopting
        r = client.get(
            f"/api/projects/{project['id']}/memory-transition/next",
            params={"agent_id": agent["id"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["entry"], dict)
        assert body["remaining"] == 2

    def test_the_route_table_offers_no_listing(self):
        """A `GET /entries` added later would defeat the ticket and would look
        like an improvement. `/plan` is the one exception: it writes nothing and
        is for a human deciding whether to begin."""
        from app.main import app

        mine = {
            (r.path, m)
            for r in app.routes
            if "memory-transition" in getattr(r, "path", "")
            for m in getattr(r, "methods", set())
            if m in ("GET", "POST")
        }
        expected = {
            ("/api/projects/{project_id}/memory-transition/plan", "GET"),
            ("/api/projects/{project_id}/memory-transition/next", "GET"),
            ("/api/projects/{project_id}/memory-transition/sweep", "POST"),
            ("/api/memory-transitions/{transition_id}/decide", "POST"),
        }
        unexpected = mine - expected
        # DWB-596 owns the derived-status read and is allowed to exist here.
        unexpected = {
            route
            for route in unexpected
            if not route[0].endswith("/memory-transition")
        }
        assert unexpected == set(), (
            f"new memory-transition route(s) {sorted(unexpected)}. Check against "
            "DWB-594: the decide phase hands over ONE entry, never the queue."
        )

    def test_next_returns_null_when_the_agent_is_done(self, client, adopting):
        project, agent, _path = adopting
        for _ in range(2):
            entry = client.get(
                f"/api/projects/{project['id']}/memory-transition/next",
                params={"agent_id": agent["id"]},
            ).json()["entry"]
            client.post(
                f"/api/memory-transitions/{entry['id']}/decide",
                json={"tier": "working", "decided_by": "tester"},
            )
        body = client.get(
            f"/api/projects/{project['id']}/memory-transition/next",
            params={"agent_id": agent["id"]},
        ).json()
        assert body["entry"] is None
        assert body["remaining"] == 0


class TestTheDecideLoopEndToEnd:
    def test_deciding_every_entry_lands_the_project(self, client, adopting):
        project, agent, _path = adopting
        landed = None
        for _ in range(2):
            entry = client.get(
                f"/api/projects/{project['id']}/memory-transition/next",
                params={"agent_id": agent["id"]},
            ).json()["entry"]
            r = client.post(
                f"/api/memory-transitions/{entry['id']}/decide",
                json={"tier": "scar", "decided_by": "tester"},
            )
            assert r.status_code == 200, r.text
            landed = r.json()["landed_in"]

        assert landed == MemoryMode.human_memory.value
        assert (
            client.get(f"/api/projects/{project['id']}").json()["memory_mode"]
            == "human_memory"
        )

    def test_core_is_refused_through_the_api(self, client, adopting):
        project, agent, _path = adopting
        entry = client.get(
            f"/api/projects/{project['id']}/memory-transition/next",
            params={"agent_id": agent["id"]},
        ).json()["entry"]
        r = client.post(
            f"/api/memory-transitions/{entry['id']}/decide",
            json={"tier": "core", "decided_by": "tester"},
        )
        assert r.status_code == 400, r.text
        assert "hard rule 5" in r.json()["detail"]

    def test_a_fully_skipped_run_is_refused_with_409(self, client, adopting):
        """The cutover guard, reached through the real API. Every entry
        journaled and none written means the store is empty."""
        project, agent, _path = adopting
        statuses = []
        for _ in range(2):
            entry = client.get(
                f"/api/projects/{project['id']}/memory-transition/next",
                params={"agent_id": agent["id"]},
            ).json()["entry"]
            r = client.post(
                f"/api/memory-transitions/{entry['id']}/decide",
                json={"decided_by": "tester", "reason": "noise"},
            )
            statuses.append(r.status_code)

        assert statuses[-1] == 409, statuses
        assert (
            client.get(f"/api/projects/{project['id']}").json()["memory_mode"]
            == "adopting"
        )

    def test_a_skip_journals_through_the_api(self, client, db_session, adopting):
        from app.models.journal_entry import JournalEntry

        project, agent, _path = adopting
        before = db_session.query(JournalEntry).count()
        entry = client.get(
            f"/api/projects/{project['id']}/memory-transition/next",
            params={"agent_id": agent["id"]},
        ).json()["entry"]
        r = client.post(
            f"/api/memory-transitions/{entry['id']}/decide",
            json={"decided_by": "tester"},
        )
        assert r.status_code == 200, r.text
        db_session.expire_all()
        assert db_session.query(JournalEntry).count() == before + 1


class TestSweepEndpoint:
    def test_the_sweep_catches_a_late_append(self, client, adopting):
        project, _agent, path = adopting
        path.write_text(FILE + "- written mid-run\n", encoding="utf-8")
        r = client.post(f"/api/projects/{project['id']}/memory-transition/sweep")
        assert r.status_code == 200, r.text
        assert r.json()["added"] == 1
        assert r.json()["is_empty"] is False

    def test_a_second_sweep_comes_back_empty(self, client, adopting):
        project, _agent, path = adopting
        path.write_text(FILE + "- written mid-run\n", encoding="utf-8")
        client.post(f"/api/projects/{project['id']}/memory-transition/sweep")
        r = client.post(f"/api/projects/{project['id']}/memory-transition/sweep")
        assert r.json()["is_empty"] is True

    def test_a_dry_sweep_writes_nothing(self, client, db_session, adopting):
        project, _agent, path = adopting
        path.write_text(FILE + "- written mid-run\n", encoding="utf-8")
        before = db_session.query(MemoryTransition).count()
        r = client.post(
            f"/api/projects/{project['id']}/memory-transition/sweep",
            params={"dry_run": True},
        )
        assert r.json()["added"] == 1
        db_session.expire_all()
        assert db_session.query(MemoryTransition).count() == before

    def test_sweeping_a_project_with_no_open_run_is_409(
        self, client, project_with_memory
    ):
        project, _agent, _path = project_with_memory
        r = client.post(f"/api/projects/{project['id']}/memory-transition/sweep")
        assert r.status_code == 409, r.text
