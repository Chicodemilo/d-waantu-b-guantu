# Path: tests/test_memory_transitions_dwb593.py
# File: test_memory_transitions_dwb593.py
# Created: 2026-09-30 (DWB-593)
# Purpose: Guard the memory-mode state machine - that yesterday's direct flip
#          is impossible, that a transition does not seal stock, that cutover
#          names what blocks it, and that abort leaves no lying rows.
# Caller: pytest
# Callees: app/services/project, app/services/memory_mode, app/models
# Data In: factory projects/agents, memory_transitions rows
# Data Out: Assertions on refusals, seal behaviour and abort cleanup
# Last Modified: 2026-09-30 (DWB-593)

"""Tests for the memory-mode transition state machine.

THE ONE THAT MATTERS MOST IS `TestTheBugIsImpossible`. Everything else in this
lane builds on a direct `stock -> human_memory` PATCH being refused, because
that flip sealed the flat file against an empty store and every agent on the
project spawned amnesiac until someone flipped it back.

`TestTheSealIsUntouched` guards the fix from its most likely wrong version. The
seal is not defective: it does exactly what DWB-589 specified, and the missing
piece was that nothing enforced its precondition. So the fix makes the sealed
state UNREACHABLE rather than giving the seal exceptions. The no-outage
property costs nothing because the backend's single `memory_mode` predicate
asks `== human_memory` rather than `!= stock` - and rewriting it as `!= stock`
would look like tidying while silently re-creating the outage on a new path.
That is why there is a test asserting the shape of one comparison.
"""

import ast
import inspect
import pathlib

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.memory_transition import (
    TERMINAL_STATES,
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import memory_mode as seal_svc
from app.services import project as svc


def _mode(db, project_id):
    return db.get(Project, project_id).memory_mode


def _set_mode(db, project_id, mode):
    """Put a project in a state directly, for tests that start mid-machine.

    Deliberately bypasses the API: these tests are about what the guard does
    FROM a state, and walking the legal path to reach it would make every test
    depend on the edges it is not testing.
    """
    db.get(Project, project_id).memory_mode = mode
    db.flush()


def _run(db, project_id, *, enumerated=True, direction=TransitionDirection.adopt):
    """An open transition run. `enumerated` defaults True because most tests
    are about something OTHER than the enumeration precondition, and leaving it
    False would make every one of them pass for the wrong reason."""
    from datetime import datetime, timezone

    row = MemoryTransitionRun(
        project_id=project_id,
        direction=direction,
        state=TransitionRunState.open,
        enumerated_at=datetime.now(timezone.utc) if enumerated else None,
    )
    db.add(row)
    db.flush()
    return row


def _transition(db, *, project_id, agent_id, state, run=None, target_memory_id=None):
    if run is None:
        # Reuse the project's open run rather than minting one per entry. The
        # database allows only one open run per project, so a helper that
        # blindly created one made a second call fail with a duplicate-key
        # error that looked like a bug in the code under test rather than in
        # the fixture. Reusing is also what real callers do.
        run = svc.open_run(db, project_id) or _run(db, project_id)
    row = MemoryTransition(
        project_id=project_id,
        agent_id=agent_id,
        run_id=run.id,
        state=state,
        target_memory_id=target_memory_id,
    )
    db.add(row)
    db.flush()
    return row


def _give_agent_memory(repo_path, prefix, agent_name, body="## Lesson\nsomething learned.\n"):
    """Write a real stock memory.md where the DWB-594 enumerator looks.

    Mirrors `memory_adopt._memory_md_path`. Without this, a factory project has
    no memory, enumeration legitimately finds nothing, and the BEGIN edge cuts
    straight through to the far side - which is correct behaviour and the wrong
    fixture for any test about a transition that has work to do.
    """
    path = pathlib.Path(repo_path) / ".dwb" / "memory" / prefix / agent_name / "memory.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def proj(db_session, make_project, make_agent, tmp_path):
    """A project whose agent HAS memory, so a transition has work to do.

    Deliberately the default: almost every test here is about a transition in
    flight, and an agent with no memory cuts straight through to the far side,
    which would make those tests pass for the wrong reason.
    """
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"])
    _give_agent_memory(tmp_path, project["prefix"], agent["name"])
    return project["id"], agent["id"]


@pytest.fixture
def empty_proj(db_session, make_project, make_agent, tmp_path):
    """A project with NO memory anywhere. Nothing to adopt."""
    project = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project["id"])
    return project["id"], agent["id"]


class TestTheBugIsImpossible:
    """ACCEPTANCE 1. Yesterday's behaviour, proved unreachable."""

    def test_direct_stock_to_human_memory_is_refused(self, client, proj):
        project_id, _ = proj
        r = client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "human_memory"},
        )
        assert r.status_code == 400
        assert "cannot go from stock to human_memory" in r.json()["detail"]

    def test_confirming_it_does_not_help(self, client, proj):
        """The old guard asked for confirmation. Confirmation was never the
        missing precondition - the missing precondition was that the content
        had moved - so confirming must not buy the illegal edge."""
        project_id, _ = proj
        r = client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "human_memory", "memory_mode_confirmed": True},
        )
        assert r.status_code == 400
        assert "cannot go from stock to human_memory" in r.json()["detail"]

    def test_the_refusal_explains_the_outage_it_prevents(self, client, proj):
        """A refusal that only says no teaches nothing. This one has to name
        the route AND why the direct flip was withdrawn, because the operator
        reading it is the person who would otherwise file a bug about it."""
        project_id, _ = proj
        detail = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        ).json()["detail"]
        assert "adopting" in detail
        assert "spawned with no memory" in detail

    def test_the_illegal_edge_is_absent_from_the_table_not_special_cased(self):
        """Refusal by ABSENCE, not by a branch. An unlisted pair refuses by
        default, so adding a state cannot accidentally permit an edge nobody
        considered; the dangerous direction of failure here is permitting."""
        assert (
            MemoryMode.stock,
            MemoryMode.human_memory,
        ) not in svc.LEGAL_MEMORY_MODE_EDGES

    @pytest.mark.parametrize(
        "frm,to",
        [
            ("stock", "reverting"),
            ("human_memory", "adopting"),
            ("human_memory", "stock"),
            ("adopting", "reverting"),
            ("reverting", "adopting"),
        ],
    )
    def test_other_nonsense_edges_are_refused_too(self, client, db_session, proj, frm, to):
        project_id, _ = proj
        _set_mode(db_session, project_id, MemoryMode(frm))
        r = client.patch(f"/api/projects/{project_id}", json={"memory_mode": to})
        assert r.status_code == 400, (frm, to)


class TestTheSealIsUntouched:
    """The no-outage property, and the edit most likely to destroy it."""

    def test_a_transitioning_project_is_not_sealed(self, db_session, proj):
        """THE WHOLE POINT. Stock stays authoritative through a transition, so
        an agent spawning mid-flight reads its memory exactly as before."""
        project_id, agent_id = proj
        for mode in (MemoryMode.adopting, MemoryMode.reverting):
            _set_mode(db_session, project_id, mode)
            project = seal_svc.project_for_agent(db_session, agent_id)
            assert seal_svc.is_human_memory(project) is False, mode

    def test_human_memory_is_still_sealed(self, db_session, proj):
        """The other half: the seal still fires where DWB-589 says it should.
        A test that only checked the transition states would pass against a
        seal that had been disabled outright."""
        project_id, agent_id = proj
        _set_mode(db_session, project_id, MemoryMode.human_memory)
        project = seal_svc.project_for_agent(db_session, agent_id)
        assert seal_svc.is_human_memory(project) is True

    def test_the_predicate_compares_equal_to_human_memory(self):
        """Asserts the SHAPE of one comparison, which is unusual and
        deliberate.

        Rewriting `== MemoryMode.human_memory` as `!= MemoryMode.stock` looks
        like cleanup and passes every behavioural test that existed before
        DWB-593, while sealing a project the moment it starts adopting -
        against a store that is still empty. That is the original amnesia bug
        on a new path. The runtime tests above catch it today; this one
        explains WHY it broke to whoever gets the failure.
        """
        source = inspect.getsource(seal_svc)
        tree = ast.parse(source)
        comparisons = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
            and any(
                isinstance(c, ast.Attribute) and c.attr in ("human_memory", "stock")
                for c in node.comparators
            )
        ]
        assert comparisons, "found no memory_mode comparison; this check saw nothing"
        for node in comparisons:
            op = node.ops[0]
            target = node.comparators[0].attr
            assert isinstance(op, ast.Eq) and target == "human_memory", (
                "the seal predicate must be `== human_memory`. `!= stock` seals "
                "adopting and reverting projects, which is the outage DWB-593 "
                "exists to make unreachable."
            )


class TestCutoverGuard:
    """ACCEPTANCE 2. Refused while work is in flight, and it says what."""

    def test_cutover_refused_while_entries_are_in_flight(
        self, client, db_session, proj
    ):
        project_id, agent_id = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        run = _run(db_session, project_id)
        _transition(
            db_session,
            project_id=project_id,
            agent_id=agent_id,
            run=run,
            state=TransitionState.pending,
        )
        r = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        )
        assert r.status_code == 400
        assert "still in flight" in r.json()["detail"]

    def test_the_refusal_names_agents_counts_and_states(
        self, client, db_session, proj, make_agent
    ):
        """A refusal that says only "not ready" leaves the operator with no
        next action, which is how a guard becomes something people route
        around. Names WHO, HOW MANY and IN WHICH STATE."""
        project_id, agent_id = proj
        other = make_agent(project_id=project_id)["id"]
        _set_mode(db_session, project_id, MemoryMode.adopting)
        run = _run(db_session, project_id)
        _transition(db_session, project_id=project_id, agent_id=agent_id, run=run, state=TransitionState.pending)
        _transition(db_session, project_id=project_id, agent_id=agent_id, run=run, state=TransitionState.pending)
        _transition(db_session, project_id=project_id, agent_id=other, run=run, state=TransitionState.pending)

        detail = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        ).json()["detail"]

        assert "3 memory transition entries" in detail
        assert "2 agents" in detail
        assert f"agent {agent_id}: 2 pending" in detail
        assert f"agent {other}: 1 pending" in detail
        # DWB-631: this asserted `1 proposed`, and the fixture above created a
        # `proposed` row to produce it. That state is gone, so `pending` is now
        # the ONLY non-terminal state and the per-agent breakdown is
        # single-valued in its state component until another is added.
        #
        # The property under test is unchanged and still exercised: the refusal
        # names WHO, HOW MANY and IN WHICH STATE. What it can no longer show is
        # two DIFFERENT non-terminal states in one message, because there are
        # no longer two to show. If a non-terminal state is ever added, restore
        # a second state here rather than leaving this reading as though the
        # message only ever reports one.

    @pytest.mark.parametrize("state", sorted(s.value for s in TERMINAL_STATES))
    def test_terminal_rows_do_not_block(self, client, db_session, proj, state):
        """Every terminal state, parametrized off TERMINAL_STATES itself, so a
        state added to that set is covered here without anyone remembering."""
        project_id, agent_id = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        _transition(
            db_session,
            project_id=project_id,
            agent_id=agent_id,
            run=_run(db_session, project_id),
            state=TransitionState(state),
        )
        r = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        )
        assert r.status_code == 200, (state, r.text)

    def test_another_projects_rows_do_not_block(
        self, client, db_session, proj, make_project, make_agent
    ):
        project_id, _ = proj
        other_project = make_project()["id"]
        other_agent = make_agent(project_id=other_project)["id"]
        _set_mode(db_session, project_id, MemoryMode.adopting)
        _run(db_session, project_id)
        _transition(
            db_session,
            project_id=other_project,
            agent_id=other_agent,
            state=TransitionState.pending,
        )
        r = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        )
        assert r.status_code == 200, r.text


class TestLegalPathAndConfirmation:
    def test_the_full_forward_sequence_works(self, client, db_session, proj):
        project_id, _ = proj
        steps = [
            ("adopting", {"memory_mode": "adopting", "memory_mode_confirmed": True}),
            ("human_memory", {"memory_mode": "human_memory"}),
            ("reverting", {"memory_mode": "reverting", "memory_mode_confirmed": True}),
            ("stock", {"memory_mode": "stock"}),
        ]
        for expected, body in steps:
            # Drive any enumerated entries to terminal before each cutover.
            # This is what "the work got done" looks like to the guard, and
            # doing it inline keeps the precondition visible: the sequence is
            # only legal because the entries finished, not because the guard
            # is lenient.
            for row in (
                db_session.query(MemoryTransition)
                .filter_by(project_id=project_id)
                .filter(MemoryTransition.state.notin_(list(TERMINAL_STATES)))
                .all()
            ):
                row.state = TransitionState.written
            db_session.flush()

            r = client.patch(f"/api/projects/{project_id}", json=body)
            assert r.status_code == 200, (expected, r.text)
            assert r.json()["memory_mode"] == expected

    def test_beginning_a_transition_still_requires_confirmation(self, client, proj):
        """The spec's warning guards the act that commits to re-reading and
        re-tiering every entry. That act is now `stock -> adopting`, so the
        DWB-588 guard moved to the renamed edge rather than being dropped."""
        project_id, _ = proj
        r = client.patch(f"/api/projects/{project_id}", json={"memory_mode": "adopting"})
        assert r.status_code == 400
        assert "rewrites every memory" in r.json()["detail"]

    def test_cutover_does_not_re_ask_for_confirmation(self, client, db_session, proj):
        """Re-asking on the continuation of a decision already confirmed once
        trains the operator to click through it, which is how a warning stops
        being read."""
        project_id, _ = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        _run(db_session, project_id)
        r = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        )
        assert r.status_code == 200, r.text

    def test_a_no_op_patch_is_not_a_transition(self, client, db_session, proj):
        project_id, _ = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        r = client.patch(f"/api/projects/{project_id}", json={"memory_mode": "adopting"})
        assert r.status_code == 200, r.text

    def test_a_patch_that_does_not_mention_memory_mode_is_untouched(
        self, client, db_session, proj
    ):
        project_id, _ = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        r = client.patch(f"/api/projects/{project_id}", json={"name": "renamed"})
        assert r.status_code == 200, r.text
        assert _mode(db_session, project_id) == MemoryMode.adopting


class TestAbort:
    """The escape hatch, and the record it leaves behind."""

    def test_abort_returns_to_where_the_transition_started(
        self, client, db_session, proj
    ):
        project_id, _ = proj
        for start, back in (
            (MemoryMode.adopting, "stock"),
            (MemoryMode.reverting, "human_memory"),
        ):
            _set_mode(db_session, project_id, start)
            r = client.patch(f"/api/projects/{project_id}", json={"memory_mode": back})
            assert r.status_code == 200, (start, r.text)
            assert r.json()["memory_mode"] == back

    def test_abort_is_not_blocked_by_in_flight_entries(self, client, db_session, proj):
        """An abort exists precisely FOR the state where work is unfinished.
        Applying the cutover guard to it would trap the operator in the
        transition they are trying to leave."""
        project_id, agent_id = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        _transition(
            db_session,
            project_id=project_id,
            agent_id=agent_id,
            run=_run(db_session, project_id, enumerated=False),
            state=TransitionState.pending,
        )
        r = client.patch(f"/api/projects/{project_id}", json={"memory_mode": "stock"})
        assert r.status_code == 200, r.text

    def test_abort_deletes_the_staging_it_wrote(self, client, db_session, proj):
        """NOT a hard rule 4 violation, and the distinction is the point. Rule
        4 protects content LEAVING memory; staged rows never ENTERED it. Stock
        is authoritative throughout a transition, so the source is still in the
        flat file and deleting staging loses nothing. Leaving it would hand a
        later adopt a half-populated store with no way to tell which rows were
        real."""
        project_id, agent_id = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        staged = AgentMemory(agent_id=agent_id, tier=MemoryTier.raw, body="staged")
        db_session.add(staged)
        db_session.flush()
        _transition(
            db_session,
            project_id=project_id,
            agent_id=agent_id,
            state=TransitionState.written,
            target_memory_id=staged.id,
        )

        client.patch(f"/api/projects/{project_id}", json={"memory_mode": "stock"})

        assert db_session.query(AgentMemory).filter_by(agent_id=agent_id).count() == 0

    def test_abort_leaves_no_row_claiming_it_landed(self, client, db_session, proj):
        """A `written` row whose memory was just deleted is a lie the next
        reader cannot detect. The first version of abort left exactly that,
        so written rows are wound back to `skipped` along with the unfinished
        ones."""
        project_id, agent_id = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        staged = AgentMemory(agent_id=agent_id, tier=MemoryTier.raw, body="staged")
        db_session.add(staged)
        db_session.flush()
        _transition(
            db_session,
            project_id=project_id,
            agent_id=agent_id,
            state=TransitionState.written,
            target_memory_id=staged.id,
        )
        _transition(
            db_session, project_id=project_id, agent_id=agent_id, state=TransitionState.pending
        )

        client.patch(f"/api/projects/{project_id}", json={"memory_mode": "stock"})

        states = [
            r.state
            for r in db_session.query(MemoryTransition)
            .filter_by(project_id=project_id)
            .all()
        ]
        assert TransitionState.written not in states
        assert states.count(TransitionState.skipped) == 2

    def test_abort_preserves_journaled_rows(self, client, db_session, proj):
        """A journaled entry left as an episode. That content is real, was
        never deleted, and winding it back to `skipped` would misreport where
        it went."""
        project_id, agent_id = proj
        _set_mode(db_session, project_id, MemoryMode.adopting)
        _transition(
            db_session,
            project_id=project_id,
            agent_id=agent_id,
            state=TransitionState.journaled,
        )

        client.patch(f"/api/projects/{project_id}", json={"memory_mode": "stock"})

        rows = db_session.query(MemoryTransition).filter_by(project_id=project_id).all()
        assert [r.state for r in rows] == [TransitionState.journaled]


class TestSchema:
    """ACCEPTANCE 3 and 4 are proved against real databases in the migration
    checks; these guard the declared shape that has to match them."""

    def test_the_two_new_modes_are_appended_last(self):
        """MySQL stores an ENUM as the ordinal of its value. Inserting a member
        in the middle renumbers `human_memory` on every existing row, which
        reads as fine until something queries by value."""
        assert [m.value for m in MemoryMode] == [
            "stock",
            "human_memory",
            "adopting",
            "reverting",
        ]

    def test_terminal_states_are_a_named_set_not_a_comparison(self):
        assert TERMINAL_STATES == frozenset(
            {
                TransitionState.written,
                TransitionState.skipped,
                TransitionState.journaled,
            }
        )
        assert TransitionState.pending not in TERMINAL_STATES
        # DWB-631 removed `proposed` and `decided`. They were never written by
        # anything and no row ever held one; they described a two-phase flow
        # section 4 rules out.
        assert not hasattr(TransitionState, "proposed")
        assert not hasattr(TransitionState, "decided")

    def test_direction_lives_on_the_run_not_on_every_entry(self):
        """Stated once instead of repeated on every entry row, which is also
        what makes an entry meaningless without its run."""
        assert "direction" not in MemoryTransition.__table__.columns
        assert "direction" in MemoryTransitionRun.__table__.columns
        assert MemoryTransition.__table__.c.run_id.nullable is False

    def test_the_run_stores_no_counts(self):
        """Entries done and total are DERIVED from memory_transitions. A stored
        count is a second authoritative copy that drifts the moment a row
        changes state without the header being updated - the same defect as a
        stored score, refused twice already in this lane."""
        cols = set(MemoryTransitionRun.__table__.columns.keys())
        for forbidden in ("entries_total", "entries_done", "agents_total", "agents_done", "count"):
            assert forbidden not in cols, forbidden

    def test_tier_vocabulary_is_reused_not_redeclared(self):
        """One definition of what a tier is. A parallel enum here would be the
        two-homes failure in miniature.

        DWB-631 dropped `proposed_tier`, so this now reads the vocabulary off
        `decided_tier`, which is the surviving tier column and the one that is
        actually written. The property under test is unchanged: the transition
        surface reuses MemoryTier rather than declaring its own.
        """
        col = MemoryTransition.__table__.c.decided_tier
        assert [e for e in col.type.enum_class] == list(MemoryTier)


def _memory_md_exists(db, project_id, agent_id) -> bool:
    from app.models.agent import Agent
    from app.services.memory_adopt import _memory_md_path

    project = db.get(Project, project_id)
    agent = db.get(Agent, agent_id)
    path = _memory_md_path(project, agent)
    return path.is_file() and bool(path.read_text(encoding="utf-8").strip())


class TestNoReachableSequenceCausesTheOutage:
    """THE CRITERION REWRITTEN AS AN OUTCOME, and the reason it had to be.

    Acceptance 1 originally said "a direct stock -> human_memory PATCH is
    refused". The first build satisfied that EXACTLY and the bug survived:
    `stock -> adopting -> human_memory` walked straight through, because a
    cutover guard that asks "is any entry unfinished" is trivially satisfied
    when there are NO entries. Two 200s, a sealed flat file and an empty store.

    Both the author and the reviewer passed it, because every individual call
    was correct and the criterion named a MECHANISM rather than the HARM. So
    these tests assert the outcome instead: no reachable sequence of calls
    leaves a project sealed against a store that was never populated.
    """

    def _sealed_with_empty_store(self, db, project_id, agent_id):
        """The HARM, stated precisely, after a first version got it wrong.

        Sealed-with-an-empty-store is not harmful on its own: a project whose
        agents have no memory has nothing to lose by being sealed, and cutting
        it straight through is correct. The harm is sealing a project whose
        agents HAD memory that never moved.

        My first version omitted the last clause and flagged the legitimate
        case as the bug. It only showed up once DWB-594's enumerator landed and
        the empty case started cutting through for real - which is the same
        mistake as the guard it is testing, made one level up: an ambiguous
        empty treated as one thing when it is two.
        """
        from app.models.agent_memory import AgentMemory

        project = db.get(Project, project_id)
        sealed = seal_svc.is_human_memory(project)
        stored = db.query(AgentMemory).filter_by(agent_id=agent_id).count()
        had_source = _memory_md_exists(db, project_id, agent_id)
        return sealed and stored == 0 and had_source

    def test_the_two_call_sequence_cannot_reach_it(self, client, db_session, proj):
        """The exact sequence that shipped the bug."""
        project_id, agent_id = proj
        client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "adopting", "memory_mode_confirmed": True},
        )
        r = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        )
        assert r.status_code == 400, "the two-call path reached human_memory"
        assert not self._sealed_with_empty_store(db_session, project_id, agent_id)

    def test_no_sequence_of_legal_edges_reaches_it(self, client, db_session, proj):
        """Walks every legal edge repeatedly, in a fixed order, asserting the
        harmful state is never reached at any point.

        Deliberately does NOT enumerate, because that is the situation the bug
        lived in: an operator driving the toggle without anything having
        populated the store. Every call is allowed to succeed or be refused;
        the only assertion is that the project is never left sealed and empty.
        """
        project_id, agent_id = proj
        edges = [e[1].value for e in svc.LEGAL_MEMORY_MODE_EDGES] * 3

        for target in edges:
            client.patch(
                f"/api/projects/{project_id}",
                json={"memory_mode": target, "memory_mode_confirmed": True},
            )
            db_session.expire_all()
            assert not self._sealed_with_empty_store(
                db_session, project_id, agent_id
            ), f"reached sealed-and-empty after patching to {target}"

    def test_cutover_is_possible_once_enumeration_has_run(
        self, client, db_session, proj
    ):
        """The other side, and it is load-bearing. A guard that never permits a
        cutover would also pass every test above while making the feature
        useless, so the permitted case is asserted in the same class as the
        refused ones.

        Zero entries after enumeration is LEGITIMATE: a project with no memory
        has nothing to move. That is precisely why the count could not be the
        precondition and a timestamp had to be.
        """
        project_id, agent_id = proj

        # Walk the entries to terminal, which is what enumeration-then-work
        # looks like from the guard's point of view.
        client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "adopting", "memory_mode_confirmed": True},
        )
        for row in (
            db_session.query(MemoryTransition).filter_by(project_id=project_id).all()
        ):
            row.state = TransitionState.written
        db_session.flush()

        r = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["memory_mode"] == "human_memory"

    def test_a_project_with_nothing_to_move_cuts_straight_through(
        self, client, db_session, empty_proj
    ):
        """The case the whole `enumerated_at` design exists to PERMIT.

        A project whose agents have no memory has nothing to adopt, so it never
        rests in `adopting` and lands directly in `human_memory`. Sealing it is
        harmless because the flat file was empty too.

        This is the other half of the ambiguous empty, and asserting it here
        stops a future tightening of the guard from making the feature
        unusable for exactly the projects it is cheapest to adopt.
        """
        project_id, agent_id = empty_proj
        r = client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "adopting", "memory_mode_confirmed": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["memory_mode"] == "human_memory"
        assert not self._sealed_with_empty_store(db_session, project_id, agent_id)

    def test_the_enumeration_guard_is_a_defensive_assertion_not_a_phase(
        self, client, db_session, proj
    ):
        """The `enumerated_at` refusal, and what it became.

        When this guard was written, enumeration was a separate act and this
        was a normal-path refusal. Enumeration is now ATOMIC with BEGIN, so the
        PATCH path cannot produce an open run with `enumerated_at` null.

        THAT IS ONE DOOR, NOT ALL OF THEM, and I first described it as
        unreachable full stop, which was wrong (Stan's correction). A run
        created by a repair script, a future direction, or a test fixture is a
        run the BEGIN edge never saw; DWB-594's own fixtures build runs that
        way. Unreachable through the path I happened to build is not
        unreachable.

        Kept for a second reason worth stating, because it argues against a
        class of future deletion rather than just this one: the bug that caused
        this rework was a cutover guard that asked the wrong question and
        passed trivially. A guard that asks the RIGHT question and is merely
        rarely exercised is a strict improvement, and "it never fires" is how
        the first one came to be written.

        The state is CONSTRUCTED here rather than walked to, which is the
        honest way to test a condition the normal path does not produce.
        """
        project_id, _ = proj
        client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "adopting", "memory_mode_confirmed": True},
        )
        run = svc.open_run(db_session, project_id)
        assert run.enumerated_at is not None, "normal operation must stamp it"

        # Now break it the way only a defect could.
        run.enumerated_at = None
        db_session.flush()

        detail = client.patch(
            f"/api/projects/{project_id}", json={"memory_mode": "human_memory"}
        ).json()["detail"]
        assert "not been enumerated" in detail
        assert "never populated" in detail


class TestRunLifecycle:
    """The entity that makes repeated transitions countable."""

    def test_beginning_a_transition_opens_a_run(self, client, db_session, proj):
        project_id, _ = proj
        client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "adopting", "memory_mode_confirmed": True},
        )
        run = svc.open_run(db_session, project_id)
        assert run is not None
        assert run.direction == TransitionDirection.adopt
        # Enumeration is ATOMIC with BEGIN, so the stamp is already set by the
        # time anyone can observe the run. It survives as the field that makes
        # the cutover guard honest, not as a phase the UI renders.
        assert run.enumerated_at is not None
        assert (
            db_session.query(MemoryTransition).filter_by(project_id=project_id).count()
            > 0
        ), "a project with memory must produce candidate rows"

    def test_a_second_open_run_is_refused_by_the_database(self, db_session, proj):
        """Enforced by a STORED generated column plus a composite UNIQUE rather
        than a read-check-write, which races."""
        import sqlalchemy.exc

        project_id, _ = proj
        _run(db_session, project_id)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            _run(db_session, project_id)
        db_session.rollback()

    def test_repeated_transitions_get_separate_runs(self, client, db_session, proj):
        """THE REASON THE RUN TABLE EXISTS. Adopt, abort, adopt again: without
        a run, the second transition's entries are indistinguishable from the
        first's, so either the audit trail is deleted or every count is wrong
        from the second transition onward."""
        project_id, _ = proj
        for _ in range(2):
            client.patch(
                f"/api/projects/{project_id}",
                json={"memory_mode": "adopting", "memory_mode_confirmed": True},
            )
            client.patch(f"/api/projects/{project_id}", json={"memory_mode": "stock"})

        runs = (
            db_session.query(MemoryTransitionRun)
            .filter_by(project_id=project_id)
            .all()
        )
        assert len(runs) == 2, "each transition must get its own run"
        assert all(r.state == TransitionRunState.aborted for r in runs)
        assert svc.open_run(db_session, project_id) is None

    def test_abort_closes_the_run(self, client, db_session, proj):
        project_id, _ = proj
        client.patch(
            f"/api/projects/{project_id}",
            json={"memory_mode": "adopting", "memory_mode_confirmed": True},
        )
        client.patch(f"/api/projects/{project_id}", json={"memory_mode": "stock"})
        run = (
            db_session.query(MemoryTransitionRun).filter_by(project_id=project_id).one()
        )
        assert run.state == TransitionRunState.aborted
        assert run.aborted_at is not None

    def test_deleting_a_project_removes_its_runs_and_entries(
        self, client, db_session, proj
    ):
        """Every FK to `projects` here is NO ACTION, so a table missing from
        the cascading delete does not fail at the model - it 500s the delete
        endpoint. Found by deleting a throwaway project and getting a 500."""
        project_id, agent_id = proj
        _transition(
            db_session,
            project_id=project_id,
            agent_id=agent_id,
            state=TransitionState.pending,
        )
        db_session.commit()
        r = client.delete(f"/api/projects/{project_id}")
        assert r.status_code == 204, r.text
