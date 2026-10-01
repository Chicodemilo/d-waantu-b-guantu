# Path: tests/test_memory_cutover_dwb594.py
# File: test_memory_cutover_dwb594.py
# Created: 2026-09-30 (DWB-594)
# Purpose: Guard automatic cutover - it fires on the last terminal row, in both
#          directions, and NEVER without proof that enumeration ran.
# Caller: pytest
# Callees: app.services.memory_cutover
# Data In: lat_test rows
# Data Out: assertions
# Last Modified: 2026-10-01 (DWB-622: refusal wording assertions updated; the
#                preserving-set test confirmed rather than changed)

"""DWB-594's cutover, by TL ruling of 2026-09-30.

The test that matters most is the one asserting a run with no `enumerated_at`
is REFUSED. That is the bug which caused this entire rework: a guard that asked
only whether rows were in flight passed trivially when there were none, and
`stock -> adopting -> human_memory` walked into an empty store in two calls.

Every other test here is ordinary. That one is the reason the module exists.
"""

import pytest

from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import memory_cutover

TERMINAL = [TransitionState.written, TransitionState.skipped, TransitionState.journaled]
# DWB-631 removed `proposed` and `decided`, so `pending` is now the only
# non-terminal state. Kept as a list rather than collapsed to a scalar: the
# parametrised tests below are the guard that a state added later has to
# declare which side of the cutover line it falls on.
NON_TERMINAL = [
    TransitionState.pending,
]


def _setup(
    db_session,
    make_project,
    make_agent,
    *,
    mode: MemoryMode,
    direction: TransitionDirection,
    states: list[TransitionState],
    enumerated: bool = True,
):
    from datetime import datetime, timezone

    project_dict = make_project()
    agent = make_agent(project_id=project_dict["id"])
    project = db_session.get(Project, project_dict["id"])
    project.memory_mode = mode

    run = MemoryTransitionRun(
        project_id=project.id,
        direction=direction,
        state=TransitionRunState.open,
        enumerated_at=(datetime.now(timezone.utc) if enumerated else None),
    )
    db_session.add(run)
    db_session.flush()

    for state in states:
        db_session.add(
            MemoryTransition(
                project_id=project.id,
                agent_id=agent["id"],
                run_id=run.id,
                state=state,
                source_excerpt="- a lesson",
            )
        )
    db_session.flush()
    return project, run


class TestTheEnumerationPrecondition:
    """The bug that caused the rework. Zero rows is not proof of anything."""

    def test_a_run_that_never_enumerated_is_refused(
        self, db_session, make_project, make_agent
    ):
        """No rows AND no enumerated_at. A guard asking only "is anything in
        flight" says yes, proceed - which is exactly how the original bug
        reached an empty store."""
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[],
            enumerated=False,
        )
        with pytest.raises(memory_cutover.CutoverRefused) as exc:
            memory_cutover.complete_if_finished(db_session, project)
        assert "enumerated_at" in str(exc.value)
        assert project.memory_mode == MemoryMode.adopting

    def test_an_enumerated_run_with_no_rows_DOES_cut_over(
        self, db_session, make_project, make_agent
    ):
        """The other side of the same coin, and the reason the precondition is
        a timestamp rather than a row count: a project with genuinely nothing to
        adopt must still be able to finish."""
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[],
            enumerated=True,
        )
        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.human_memory
        )

    def test_the_refusal_does_not_half_complete_the_run(
        self, db_session, make_project, make_agent
    ):
        project, run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[],
            enumerated=False,
        )
        with pytest.raises(memory_cutover.CutoverRefused):
            memory_cutover.complete_if_finished(db_session, project)
        assert run.state == TransitionRunState.open
        assert run.completed_at is None


class TestAllTerminalIsNotAllSurvived:
    """Barry's find: an entry reaches terminal by being written, skipped OR
    journaled, and only two of those preserve anything.

    A run where every entry was skipped is fully terminal with nothing kept, so
    cutting over seals the flat file against an empty store. The agent had
    memory, has none, and cannot read the file that still holds it. That is
    indistinguishable from a bug that skipped everything, and this lane exists
    because a state indistinguishable from a bug reached production.
    """

    def test_a_fully_skipped_run_is_refused(
        self, db_session, make_project, make_agent
    ):
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.skipped, TransitionState.skipped],
        )
        with pytest.raises(memory_cutover.CutoverRefused) as exc:
            memory_cutover.complete_if_finished(db_session, project)
        # DWB-622 changed the WORDING, not the outcome. The old text asserted
        # "every one was skipped ... nothing was journaled", which was false
        # whenever the skips went through memory_decide.skip() - every skip
        # journals first. The refusal now reports measured state counts.
        assert "skipped: 2" in str(exc.value)
        assert "nothing was journaled" not in str(exc.value)
        assert project.memory_mode == MemoryMode.adopting

    def test_one_written_row_is_enough_to_proceed(
        self, db_session, make_project, make_agent
    ):
        """Skipping most of a file is an ordinary, deliberate outcome. Only
        preserving NOTHING is the defect, so the guard must not become a
        general objection to skipping."""
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[
                TransitionState.skipped,
                TransitionState.skipped,
                TransitionState.written,
            ],
        )
        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.human_memory
        )

    def test_one_journaled_row_is_also_enough(
        self, db_session, make_project, make_agent
    ):
        """`journaled` preserves the entry too - spec section 7 hard rule 4
        makes the journal where anything leaving memory goes first. An entry
        that left as an episode was not lost.

        DWB-622 briefly reversed this test and then put it back. Recorded
        because the reversal was wrong for a reason that is easy to re-derive:
        `journaled` is how a REVERT run reaches its destination, so removing it
        from the preserving set refuses every legitimate revert
        (`test_a_revert_lands_in_stock` is the one that caught it). The
        preserving set is a union across both directions, not a statement about
        the adopt store alone.
        """
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.skipped, TransitionState.journaled],
        )
        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.human_memory
        )

    def test_a_zero_candidate_run_still_cuts_over(
        self, db_session, make_project, make_agent
    ):
        """Nothing enumerated is a DIFFERENT case from everything skipped, and
        it is legitimate. Sweeping both into one refusal would trap every
        project that genuinely has no memory to adopt."""
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[],
        )
        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.human_memory
        )

    def test_the_preserving_set_excludes_only_skipped(self):
        """Pinned against TERMINAL_STATES so a terminal state added later has to
        declare whether it puts the entry in the NEW STORE, rather than
        defaulting into the safe-looking side and silently permitting an empty
        cutover.

        DWB-622 confirmed this set rather than changing it. The set is a union
        across both DIRECTIONS - `written` is how an adopt reaches its
        destination, `journaled` is how a revert reaches its - which is why
        narrowing it to `{written}` breaks reverts.
        """
        from app.models.memory_transition import TERMINAL_STATES

        assert memory_cutover._PRESERVING_STATES < TERMINAL_STATES
        assert TERMINAL_STATES - memory_cutover._PRESERVING_STATES == {
            TransitionState.skipped
        }


class TestFiresOnTheLastTerminalRow:
    @pytest.mark.parametrize("last_state", TERMINAL)
    def test_every_terminal_state_completes_the_run(
        self, db_session, make_project, make_agent, last_state
    ):
        """Parametrized over the terminal set itself, so a state added to
        TERMINAL_STATES without thought here surfaces rather than silently
        failing to trigger a cutover."""
        project, run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.written, last_state],
        )
        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.human_memory
        )
        assert run.state == TransitionRunState.completed
        assert run.completed_at is not None

    @pytest.mark.parametrize("pending_state", NON_TERMINAL)
    def test_one_unfinished_row_holds_the_cutover(
        self, db_session, make_project, make_agent, pending_state
    ):
        project, run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.written, pending_state],
        )
        assert memory_cutover.complete_if_finished(db_session, project) is None
        assert project.memory_mode == MemoryMode.adopting
        assert run.state == TransitionRunState.open

    def test_rows_from_another_run_do_not_hold_this_one(
        self, db_session, make_project, make_agent
    ):
        """A project that adopts, reverts and adopts again has rows from earlier
        runs. Counting them would make every transition after the first
        impossible to finish - the defect the run table was added to prevent."""
        project, run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.written],
        )
        stale = MemoryTransitionRun(
            project_id=project.id,
            direction=TransitionDirection.adopt,
            state=TransitionRunState.completed,
        )
        db_session.add(stale)
        db_session.flush()
        db_session.add(
            MemoryTransition(
                project_id=project.id,
                agent_id=db_session.query(MemoryTransition).first().agent_id,
                run_id=stale.id,
                state=TransitionState.pending,
                source_excerpt="- an old row nobody will finish",
            )
        )
        db_session.flush()

        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.human_memory
        )


class TestBothDirections:
    def test_a_revert_lands_in_stock(self, db_session, make_project, make_agent):
        project, run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.reverting,
            direction=TransitionDirection.revert,
            states=[TransitionState.journaled],
        )
        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.stock
        )
        assert run.state == TransitionRunState.completed

    def test_direction_and_mode_disagreeing_is_refused(
        self, db_session, make_project, make_agent
    ):
        """An adopt run on a reverting project means something moved the mode
        outside the state machine. Landing anyway would apply a cutover the
        legal-edge table does not define."""
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.reverting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.written],
        )
        with pytest.raises(memory_cutover.CutoverRefused) as exc:
            memory_cutover.complete_if_finished(db_session, project)
        assert "not a cutover edge" in str(exc.value)

    def test_the_landing_table_covers_every_direction(self):
        """A direction added later must state where it lands rather than
        falling through to a default."""
        assert set(memory_cutover._LANDING) == set(TransitionDirection)


class TestTheFinalSweep:
    """DWB-594 acceptance 4: cutover happens only after a sweep returns empty.

    Without it, a lesson written between the last decision and the flip is
    enumerated by nobody and sealed away unread. The judgement loop is long and
    memory keeps being written throughout, which is exactly why the loop is not
    the freeze.
    """

    def test_a_late_arrival_abandons_the_cutover(
        self, db_session, make_project, make_agent, tmp_path
    ):
        from pathlib import Path

        from app.services import memory_adopt

        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="Latecomer")
        d = Path(tmp_path) / ".dwb" / "memory" / project_dict["prefix"] / "Latecomer"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "memory.md"
        path.write_text("## Topic\n- the first lesson\n", encoding="utf-8")

        project = db_session.get(Project, project_dict["id"])
        project.memory_mode = MemoryMode.adopting
        run = MemoryTransitionRun(
            project_id=project.id,
            direction=TransitionDirection.adopt,
            state=TransitionRunState.open,
        )
        db_session.add(run)
        db_session.flush()
        memory_adopt.enumerate_for_run(db_session, project=project, run=run)
        run.enumerated_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )

        for row in db_session.query(MemoryTransition).filter_by(run_id=run.id):
            row.state = TransitionState.written
        db_session.flush()

        # Written after the last decision, before the flip.
        path.write_text(
            "## Topic\n- the first lesson\n- written just before the flip\n",
            encoding="utf-8",
        )

        assert memory_cutover.complete_if_finished(db_session, project) is None, (
            "the project cut over while a lesson written during the transition "
            "had been enumerated by nobody; it would be sealed away unread"
        )
        assert project.memory_mode == MemoryMode.adopting
        assert (
            db_session.query(MemoryTransition).filter_by(run_id=run.id).count() == 2
        )

    def test_an_empty_final_sweep_lets_the_cutover_proceed(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """The positive, so the test above is not passing because the sweep
        always blocks."""
        from pathlib import Path

        from app.services import memory_adopt

        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="Settled")
        d = Path(tmp_path) / ".dwb" / "memory" / project_dict["prefix"] / "Settled"
        d.mkdir(parents=True, exist_ok=True)
        (d / "memory.md").write_text("## Topic\n- the only lesson\n", encoding="utf-8")

        project = db_session.get(Project, project_dict["id"])
        project.memory_mode = MemoryMode.adopting
        run = MemoryTransitionRun(
            project_id=project.id,
            direction=TransitionDirection.adopt,
            state=TransitionRunState.open,
        )
        db_session.add(run)
        db_session.flush()
        memory_adopt.enumerate_for_run(db_session, project=project, run=run)
        run.enumerated_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        for row in db_session.query(MemoryTransition).filter_by(run_id=run.id):
            row.state = TransitionState.written
        db_session.flush()

        assert (
            memory_cutover.complete_if_finished(db_session, project)
            == MemoryMode.human_memory
        )


class TestOrdinaryNegatives:
    def test_no_open_run_is_not_an_error(self, db_session, make_project):
        project = db_session.get(Project, make_project()["id"])
        assert memory_cutover.complete_if_finished(db_session, project) is None

    def test_calling_twice_is_safe(self, db_session, make_project, make_agent):
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.written],
        )
        first = memory_cutover.complete_if_finished(db_session, project)
        second = memory_cutover.complete_if_finished(db_session, project)
        assert first == MemoryMode.human_memory
        assert second is None, "a second call re-fired against a completed run"

    def test_it_does_not_commit(self, db_session, make_project, make_agent):
        """The caller owns the transaction, so a cutover and the decision that
        triggered it land together or not at all."""
        project, _run = _setup(
            db_session,
            make_project,
            make_agent,
            mode=MemoryMode.adopting,
            direction=TransitionDirection.adopt,
            states=[TransitionState.written],
        )
        import unittest.mock as mock

        with mock.patch.object(
            db_session, "commit", side_effect=AssertionError("committed")
        ):
            memory_cutover.complete_if_finished(db_session, project)
