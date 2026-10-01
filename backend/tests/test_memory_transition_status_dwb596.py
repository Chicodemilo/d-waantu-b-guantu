# Path:          tests/test_memory_transition_status_dwb596.py
# File:          test_memory_transition_status_dwb596.py
# Created:       2026-09-30
# Purpose:       DWB-596 - GET /api/projects/{id}/memory-transition computes its status from
#                row states on every request, distinguishes every "empty" case from every
#                other, names the agents in its breakdown, and has NO write path anywhere
# Caller:        pytest
# Callees:       GET /api/projects/:id/memory-transition, app.services.memory_transition,
#                app.models.memory_transition
# Data In:       Factory-created projects/agents plus transition runs and rows written directly
# Data Out:      Assertions on the derived status, and on the absence of a status write path
# Last Modified: 2026-10-01 (DWB-622: written+skipped partition done, with
#                entries_journaled as an overlay over it rather than a third bucket)

"""DWB-596: the status is derived, and there is nothing to write it with.

TWO KINDS OF TEST LIVE HERE.

TestDerivedFromRows and the status-vocabulary classes name the defects: a count
that cannot tell "found nothing" from "never ran", a status that goes stale
because it was stored, a breakdown that says how many rows remain without
saying whose. Break the computation and they go red.

TestNoWritePathExists is different in kind. It does not exercise behaviour at
all; it asserts the ABSENCE of a capability, which is Miles's actual
requirement. A rule in prose saying agents must not post status updates holds
until the day it does not, and it fails silently because a stale status looks
exactly like a live one. So the capability must not exist, and this is the only
kind of test that can check that.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.memory_transition import (
    TERMINAL_STATES,
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)


# ---------------------------------------------------------------------------
# Fixtures: runs and rows are written DIRECTLY, not through an API, because
# nothing in this ticket may create them and the enumerator that does is
# DWB-594. Building them here keeps this suite testing the read path rather
# than another ticket's write path.
# ---------------------------------------------------------------------------


@pytest.fixture
def make_run(db_session):
    def _make(project_id, *, enumerated=True, state=TransitionRunState.open,
              direction=TransitionDirection.adopt):
        run = MemoryTransitionRun(
            project_id=project_id,
            direction=direction,
            state=state,
            started_at=datetime(2026, 9, 30, 10, 0, 0),
            enumerated_at=(
                datetime(2026, 9, 30, 10, 0, 5) if enumerated else None
            ),
        )
        db_session.add(run)
        db_session.commit()
        db_session.refresh(run)
        return run
    return _make


@pytest.fixture
def make_rows(db_session):
    def _make(run, agent_id, states):
        made = []
        for st in states:
            row = MemoryTransition(
                project_id=run.project_id,
                agent_id=agent_id,
                run_id=run.id,
                state=st,
            )
            db_session.add(row)
            made.append(row)
        db_session.commit()
        return made
    return _make


# Every non-GET route on the transition surface, with WHY it may write.
#
# THE THING THIS TICKET FORBIDS IS A WRITABLE STATUS, not writes in general.
# The pipeline has to write entries or nothing would ever progress; what must
# not exist is a way to post a status, because a status that can be written is
# one that can be stale while looking live. Each entry below therefore says why
# that endpoint is not writing one.
TRANSITION_WRITERS: dict[str, str] = {
    "/api/memory-transitions/{transition_id}/decide": (
        "DWB-594: records one entry's decided tier. Writes ENTRIES, and on the "
        "FINAL entry also the run's completion and the project's mode, all in "
        "ONE TRANSACTION with the entry state that implies them. The atomicity "
        "is the property doing the work here, not derivation: the run can "
        "never disagree with its entries because it is only ever written "
        "together with the fact that makes it true. A run write placed OUTSIDE "
        "that transaction would break this reason even though the endpoint "
        "still only wrote entries and a run. (Corrected by Stan, who wrote it; "
        "my first version said 'writes the ENTRY, never a status', which was "
        "true of the status and wrong about what the call touches.)"
    ),
    "/api/projects/{project_id}/memory-transition/sweep": (
        "DWB-594: advances enumerated entries through the pipeline. Writes "
        "entry states only, in bulk, and every count the status reports is "
        "derived from those rows at read time, so there is nothing here that "
        "could go stale relative to them."
    ),
}


def _status(client, project_id):
    r = client.get(f"/api/projects/{project_id}/memory-transition")
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# AC3 + the DWB-585 distinction: every "empty" case is its own value
# ---------------------------------------------------------------------------


class TestEmptyIsNeverOneAnswer:
    def test_never_transitioned_is_not_started(self, client, make_project):
        project = make_project()
        assert _status(client, project["id"])["status"] == "not_started"

    def test_transitioned_and_finished_is_idle_not_not_started(
        self, client, make_project, make_run
    ):
        # The case that caught me on a live probe: a project whose transition
        # completed instantly reported "not_started" about a transition it had
        # just finished. Both have no open run; they are not the same thing.
        project = make_project()
        make_run(project["id"], state=TransitionRunState.completed)
        assert _status(client, project["id"])["status"] == "idle"

    def test_open_run_without_enumeration_is_not_enumerated(
        self, client, make_project, make_run
    ):
        # A count of zero cannot tell "enumeration ran and found nothing" from
        # "enumeration never ran". The first is a legitimate cutover, the
        # second is the bug the run table was added to catch.
        project = make_project()
        make_run(project["id"], enumerated=False)
        body = _status(client, project["id"])
        assert body["status"] == "not_enumerated"
        assert body["entries_total"] == 0

    def test_enumerated_with_no_candidates_is_complete_not_not_enumerated(
        self, client, make_project, make_run
    ):
        # Same zero count, opposite meaning. This is the pair that a single
        # "empty" answer would collapse.
        project = make_project()
        make_run(project["id"], enumerated=True)
        assert _status(client, project["id"])["status"] == "complete"

    def test_all_five_values_are_reachable_and_distinct(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        seen = set()

        p1 = make_project()
        seen.add(_status(client, p1["id"])["status"])

        p2 = make_project()
        make_run(p2["id"], state=TransitionRunState.completed)
        seen.add(_status(client, p2["id"])["status"])

        p3 = make_project()
        make_run(p3["id"], enumerated=False)
        seen.add(_status(client, p3["id"])["status"])

        p4 = make_project()
        run4 = make_run(p4["id"])
        a4 = make_agent(project_id=p4["id"])
        make_rows(run4, a4["id"], [TransitionState.pending, TransitionState.written])
        seen.add(_status(client, p4["id"])["status"])

        p5 = make_project()
        run5 = make_run(p5["id"])
        a5 = make_agent(project_id=p5["id"])
        make_rows(run5, a5["id"], [TransitionState.written])
        seen.add(_status(client, p5["id"])["status"])

        assert seen == {
            "not_started", "idle", "not_enumerated", "in_progress", "complete"
        }


# ---------------------------------------------------------------------------
# AC1: computed from row states on every request
# ---------------------------------------------------------------------------


class TestDerivedFromRows:
    def test_response_changes_when_a_row_state_changes(
        self, client, db_session, make_project, make_agent, make_run, make_rows
    ):
        # AC1 exactly: the only thing that happens between the two reads is a
        # ROW changing state. Nothing writes a status, because nothing can.
        project = make_project()
        run = make_run(project["id"])
        agent = make_agent(project_id=project["id"])
        rows = make_rows(
            run, agent["id"], [TransitionState.pending, TransitionState.pending]
        )

        before = _status(client, project["id"])
        assert before["status"] == "in_progress"
        assert before["entries_done"] == 0

        rows[0].state = TransitionState.written
        db_session.commit()

        after = _status(client, project["id"])
        assert after["entries_done"] == 1
        assert after["status"] == "in_progress"

        rows[1].state = TransitionState.skipped
        db_session.commit()

        final = _status(client, project["id"])
        assert final["entries_done"] == 2
        assert final["status"] == "complete"

    @pytest.mark.parametrize("state", sorted(s.value for s in TERMINAL_STATES))
    def test_every_terminal_state_counts_as_done(
        self, client, make_project, make_agent, make_run, make_rows, state
    ):
        # Borrows TERMINAL_STATES rather than restating it, so adding a state
        # to the guard's vocabulary cannot leave this display disagreeing with
        # the guard about what "done" means.
        project = make_project()
        run = make_run(project["id"])
        agent = make_agent(project_id=project["id"])
        make_rows(run, agent["id"], [TransitionState(state)])
        assert _status(client, project["id"])["entries_done"] == 1

    @pytest.mark.parametrize(
        "state",
        sorted(s.value for s in TransitionState if s not in TERMINAL_STATES),
    )
    def test_no_non_terminal_state_counts_as_done(
        self, client, make_project, make_agent, make_run, make_rows, state
    ):
        project = make_project()
        run = make_run(project["id"])
        agent = make_agent(project_id=project["id"])
        make_rows(run, agent["id"], [TransitionState(state)])
        body = _status(client, project["id"])
        assert body["entries_done"] == 0
        assert body["status"] == "in_progress"


# ---------------------------------------------------------------------------
# AC4: the breakdown names who
# ---------------------------------------------------------------------------


class TestPerAgentBreakdown:
    def test_names_the_agent_blocking_the_transition(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        # "14 of 51 done" tells an operator to wait. "this agent has 0 of 2"
        # tells them who to ask, which is the difference the AC is after.
        project = make_project()
        run = make_run(project["id"])
        quick = make_agent(project_id=project["id"])
        stalled = make_agent(project_id=project["id"])
        make_rows(run, quick["id"], [TransitionState.written, TransitionState.written])
        make_rows(run, stalled["id"], [TransitionState.pending, TransitionState.pending])

        body = _status(client, project["id"])
        by_id = {a["agent_id"]: a for a in body["agents"]}

        assert by_id[quick["id"]]["agent_name"] == quick["name"]
        assert by_id[quick["id"]]["done"] is True
        assert by_id[stalled["id"]]["agent_name"] == stalled["name"]
        assert by_id[stalled["id"]]["done"] is False
        assert by_id[stalled["id"]]["entries_done"] == 0
        assert by_id[stalled["id"]]["entries_total"] == 2

        assert body["agents_total"] == 2
        assert body["agents_done"] == 1

    def test_breakdown_totals_agree_with_the_headline_totals(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        # Two numbers for the same fact, on one screen, is how a reader learns
        # not to trust either.
        project = make_project()
        run = make_run(project["id"])
        a1 = make_agent(project_id=project["id"])
        a2 = make_agent(project_id=project["id"])
        make_rows(run, a1["id"], [TransitionState.written, TransitionState.pending])
        make_rows(run, a2["id"], [TransitionState.skipped])

        body = _status(client, project["id"])
        assert body["entries_total"] == sum(a["entries_total"] for a in body["agents"])
        assert body["entries_done"] == sum(a["entries_done"] for a in body["agents"])


# ---------------------------------------------------------------------------
# Done is not the same as landed
# ---------------------------------------------------------------------------


class TestOutcomeBreakdown:
    """A run that discarded everything is complete and moved nothing.

    Raised by the guard's owner against a first version that reported only
    `entries_done`. All three of written, journaled and skipped are terminal,
    correctly, because the guard asks only whether the cutover may proceed. A
    human deciding whether to CONFIRM one is asking a different question, and
    "51 of 51 done" answers it wrongly when all 51 were skipped.
    """

    def test_a_run_that_skipped_everything_is_complete_but_wrote_nothing(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        project = make_project()
        run = make_run(project["id"])
        agent = make_agent(project_id=project["id"])
        make_rows(run, agent["id"], [TransitionState.skipped] * 3)

        body = _status(client, project["id"])
        # Complete is CORRECT: the cutover may proceed, and skipping
        # everything is a legitimate choice rather than a failure.
        assert body["status"] == "complete"
        assert body["entries_done"] == 3
        # And this is what stops it reading as a successful migration.
        assert body["entries_written"] == 0
        assert body["entries_skipped"] == 3

    def test_journaled_entries_are_done_but_not_written(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        # Milder version of the same shape: journaled entries went somewhere
        # real, but they are not in the new store.
        project = make_project()
        run = make_run(project["id"])
        agent = make_agent(project_id=project["id"])
        make_rows(run, agent["id"], [TransitionState.journaled] * 2)

        body = _status(client, project["id"])
        assert body["entries_done"] == 2
        assert body["entries_written"] == 0
        assert body["entries_journaled"] == 2

    def test_written_and_skipped_partition_done_with_journaled_as_an_overlay(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        """DWB-622 changed what these three mean, so this assertion changed
        with it.

        It used to add all three and expect `entries_done`. That only held
        while `journaled` was unreachable: the moment the counter started
        seeing skips - which are journaled before they go terminal - the three
        overlapped and the sum double-counted. `written` and `skipped`
        PARTITION the terminal rows; `entries_journaled` is an OVERLAY over
        that partition counting whatever reached the journal, so it is checked
        against its own members rather than added alongside them.
        """
        project = make_project()
        run = make_run(project["id"])
        agent = make_agent(project_id=project["id"])
        make_rows(run, agent["id"], [
            TransitionState.written,
            TransitionState.written,
            TransitionState.journaled,
            TransitionState.skipped,
            TransitionState.pending,
        ])

        body = _status(client, project["id"])
        assert body["entries_total"] == 5
        assert body["entries_done"] == 4
        assert body["entries_written"] == 2
        assert body["entries_skipped"] == 1
        # The partition.
        assert (
            body["entries_written"] + body["entries_skipped"]
            + 1  # the legacy `journaled` row, terminal but in neither bucket
        ) == body["entries_done"]
        # The overlay: one legacy journaled row plus one skip, both of whose
        # content is in the journal.
        assert body["entries_journaled"] == 2

    def test_non_terminal_rows_land_in_no_outcome_bucket(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        project = make_project()
        run = make_run(project["id"])
        agent = make_agent(project_id=project["id"])
        make_rows(run, agent["id"], [
            TransitionState.pending,
        ])

        body = _status(client, project["id"])
        assert body["entries_done"] == 0
        assert body["entries_written"] == 0
        assert body["entries_journaled"] == 0
        assert body["entries_skipped"] == 0


# ---------------------------------------------------------------------------
# AC2: the absence of a capability
# ---------------------------------------------------------------------------


class TestNoWritePathExists:
    """Miles's requirement, held structurally rather than by a rule.

    These assert that nothing CAN write a status. They are not behaviour tests
    and they will look strange next to the others; that is the point. A rule
    saying "agents must not post status updates" is followed until it is not,
    and a stale status is indistinguishable from a live one.
    """

    def test_no_status_column_on_either_transition_table(self):
        for model in (MemoryTransitionRun, MemoryTransition):
            columns = set(model.__table__.columns.keys())
            for forbidden in ("status", "status_text", "progress", "summary"):
                assert forbidden not in columns, (
                    f"{model.__tablename__}.{forbidden} exists; a stored status "
                    "is a second authoritative copy that goes stale silently"
                )

    def test_the_status_route_is_read_only(self):
        from app.main import app

        routes = [
            r for r in app.routes
            if getattr(r, "path", "") == "/api/projects/{project_id}/memory-transition"
        ]
        assert routes, "the status route is missing"
        for route in routes:
            assert set(route.methods) == {"GET"}, (
                f"{route.methods} on the status route; it must be readable only"
            )

    def test_every_writer_on_the_transition_surface_is_declared(self):
        """An ALLOWLIST WITH REASONS, not a ban with exceptions.

        This started as "no non-GET route may contain memory-transition",
        which was wrong: the pipeline legitimately writes ENTRIES, and DWB-594
        and DWB-595 need those endpoints. But loosening it to a prefix split
        would have permitted a whole class of future writer sight unseen,
        including one nobody would want.

        What this ticket actually forbids is a writable STATUS. So every
        writer is named here with why it is not one, and adding a writer means
        adding a line and stating a reason. That is a deliberate act a
        reviewer sees, rather than a test quietly going green because the new
        path happened to fall on the permitted side of a split.

        Ruled by Archie after Barry's suite run caught it and Stan found the
        detail that settles it: the intent here is already asserted twice, by
        the GET-only route test above and the AST write-verb test below, so
        what this case adds is coverage of a writer somewhere ELSE in the app.
        An allowlist is the only shape that covers that without also blessing
        whatever lands next.
        """
        from app.main import app

        declared = set(TRANSITION_WRITERS)
        found = {
            getattr(route, "path", "")
            for route in app.routes
            if "memory-transition" in getattr(route, "path", "")
            and (getattr(route, "methods", set()) or set()) - {"GET", "HEAD", "OPTIONS"}
        }

        undeclared = found - declared
        assert not undeclared, (
            "these write to the transition surface and are not declared in "
            f"TRANSITION_WRITERS: {sorted(undeclared)}. If the new endpoint "
            "writes ENTRIES, add it with the reason it is not writing a "
            "status. If it writes a status, this ticket says it must not exist."
        )

        # A stale entry is worse than a missing one: it pre-authorises a future
        # route that reuses the path, carrying a reason written about something
        # else entirely.
        stale = declared - found
        assert not stale, (
            f"TRANSITION_WRITERS names routes that no longer exist: {sorted(stale)}. "
            "Remove them rather than leaving a standing permission."
        )

    def test_every_declared_writer_gives_an_actual_reason(self):
        # The forcing function is mechanical, so "ok" does not pass for one.
        for path, reason in TRANSITION_WRITERS.items():
            assert len(reason.strip()) >= 40, (
                f"{path} is allowlisted with no real reason: {reason!r}"
            )

    def test_the_service_module_contains_no_write(self):
        # Read the source rather than trusting the review that read it once.
        # A commit, add, flush, delete or execute of a mutation in here would
        # mean the read path can change what it reports on.
        import ast
        import inspect

        from app.services import memory_transition as svc

        tree = ast.parse(inspect.getsource(svc))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        for forbidden in ("commit", "add", "add_all", "flush", "delete", "merge"):
            assert forbidden not in called, (
                f"app/services/memory_transition.py calls {forbidden}(); the "
                "status service must not be able to write anything"
            )

    def test_the_schema_module_exposes_no_create_or_update_model(self):
        import app.schemas.memory_transition as schema_mod

        names = [n for n in dir(schema_mod) if not n.startswith("_")]
        for name in names:
            assert not name.endswith("Create"), f"{name} would be a write shape"
            assert not name.endswith("Update"), f"{name} would be a write shape"


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------


class TestScoping:
    def test_another_project_run_does_not_leak(
        self, client, make_project, make_agent, make_run, make_rows
    ):
        mine = make_project()
        theirs = make_project()
        run = make_run(theirs["id"])
        agent = make_agent(project_id=theirs["id"])
        make_rows(run, agent["id"], [TransitionState.pending])

        assert _status(client, mine["id"])["status"] == "not_started"
        assert _status(client, theirs["id"])["status"] == "in_progress"

    def test_a_missing_project_is_404_not_a_null_status(self, client):
        # An unknown project is an error. A project with no transition is not.
        r = client.get("/api/projects/99999999/memory-transition")
        assert r.status_code == 404

    def test_rows_from_an_earlier_run_do_not_count(
        self, client, db_session, make_project, make_agent, make_run, make_rows
    ):
        # The second reason the run table exists: a project that adopts,
        # reverts and adopts again has rows nothing else distinguishes, and
        # every count would be wrong from the second transition onward.
        project = make_project()
        agent = make_agent(project_id=project["id"])
        old = make_run(project["id"], state=TransitionRunState.completed)
        make_rows(old, agent["id"], [TransitionState.written] * 5)
        current = make_run(project["id"])
        make_rows(current, agent["id"], [TransitionState.pending])

        body = _status(client, project["id"])
        assert body["entries_total"] == 1
        assert body["entries_done"] == 0
        assert body["run_id"] == current.id
