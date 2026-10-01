# Path: tests/test_memory_sweep_dwb594.py
# File: test_memory_sweep_dwb594.py
# Created: 2026-09-30 (DWB-594)
# Purpose: Guard the sweep - it catches an entry appended mid-run, never
#          re-adds what is already enumerated, and handles duplicates as a
#          multiset rather than a set.
# Caller: pytest
# Callees: app.services.memory_sweep
# Data In: lat_test rows plus memory.md files under tmp_path
# Data Out: assertions
# Last Modified: 2026-09-30 (DWB-594)

"""DWB-594 phase 4, acceptance 3: the sweep catches an entry appended after the
snapshot, proved by appending one mid-run.

The subtler tests are the two about NOT re-adding: a sweep that re-enumerates
rows it already has never comes back empty, so the loop never terminates and the
cutover never fires. And the duplicate test, because the obvious implementation
(a set difference) silently drops a genuine second copy forever.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import Project
from app.services import memory_adopt, memory_sweep

SNAPSHOT = "## Verification\n- a green run and a recorded run differ\n"


def _write(tmp_path, prefix, name, text):
    d = Path(tmp_path) / ".dwb" / "memory" / prefix / name
    d.mkdir(parents=True, exist_ok=True)
    path = d / "memory.md"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def mid_run(db_session, make_project, make_agent, tmp_path):
    """A project whose snapshot has been taken and whose file is on disk."""
    project_dict = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project_dict["id"], name="Sweeper")
    path = _write(tmp_path, project_dict["prefix"], "Sweeper", SNAPSHOT)
    project = db_session.get(Project, project_dict["id"])

    run = MemoryTransitionRun(
        project_id=project.id,
        direction=TransitionDirection.adopt,
        state=TransitionRunState.open,
        enumerated_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.flush()
    memory_adopt.enumerate_for_run(db_session, project=project, run=run)
    return project, agent, run, path


class TestCatchesWhatArrivedLate:
    """Acceptance 3, by appending mid-run exactly as the ticket asks."""

    def test_an_entry_appended_after_the_snapshot_is_caught(
        self, db_session, mid_run
    ):
        project, _agent, run, path = mid_run
        before = db_session.query(MemoryTransition).filter_by(run_id=run.id).count()

        path.write_text(
            SNAPSHOT + "- written while the judging was happening\n", encoding="utf-8"
        )
        result = memory_sweep.sweep(db_session, project, run)

        assert result.added_count == 1, [r.source_excerpt for r in result.added]
        assert "while the judging" in result.added[0].source_excerpt
        assert (
            db_session.query(MemoryTransition).filter_by(run_id=run.id).count()
            == before + 1
        )
        assert result.added[0].state == TransitionState.pending

    def test_a_sweep_with_no_new_content_comes_back_empty(self, db_session, mid_run):
        """The loop's termination condition. Without it the cutover never
        fires, because the sweep is repeated until it adds nothing."""
        project, _agent, run, _path = mid_run
        result = memory_sweep.sweep(db_session, project, run)
        assert result.is_empty
        assert result.added_count == 0

    def test_repeated_sweeps_do_not_re_add(self, db_session, mid_run):
        """A sweep that re-enumerates what it already has never comes back
        empty, so the loop never terminates."""
        project, _agent, run, path = mid_run
        path.write_text(SNAPSHOT + "- a late arrival\n", encoding="utf-8")

        first = memory_sweep.sweep(db_session, project, run)
        second = memory_sweep.sweep(db_session, project, run)
        third = memory_sweep.sweep(db_session, project, run)

        assert first.added_count == 1
        assert second.is_empty
        assert third.is_empty


class TestAlreadyDecidedRowsCount:
    @pytest.mark.parametrize(
        "state",
        [TransitionState.written, TransitionState.skipped, TransitionState.journaled],
    )
    def test_a_terminal_row_is_not_re_enumerated(self, db_session, mid_run, state):
        """The comparison is against EVERY row in the run, not just pending
        ones. Otherwise each sweep re-adds everything already decided and the
        loop never comes back empty."""
        project, _agent, run, _path = mid_run
        row = db_session.query(MemoryTransition).filter_by(run_id=run.id).one()
        row.state = state
        db_session.flush()

        assert memory_sweep.sweep(db_session, project, run).is_empty

    def test_a_decided_row_is_not_resurrected_by_a_later_sweep(
        self, db_session, mid_run
    ):
        project, _agent, run, path = mid_run
        row = db_session.query(MemoryTransition).filter_by(run_id=run.id).one()
        row.state = TransitionState.skipped
        db_session.flush()

        path.write_text(SNAPSHOT + "- something new\n", encoding="utf-8")
        result = memory_sweep.sweep(db_session, project, run)

        assert result.added_count == 1
        assert "something new" in result.added[0].source_excerpt
        assert row.state == TransitionState.skipped


class TestDuplicatesAreAMultisetNotASet:
    """The obvious implementation drops a genuine second copy forever."""

    def test_a_second_identical_lesson_gets_its_own_row(self, db_session, mid_run):
        project, _agent, run, path = mid_run
        path.write_text(
            "## Verification\n"
            "- a green run and a recorded run differ\n"
            "- a green run and a recorded run differ\n",
            encoding="utf-8",
        )
        result = memory_sweep.sweep(db_session, project, run)

        assert result.added_count == 1, (
            "the duplicate was swallowed by a set comparison; the agent wrote "
            "the lesson twice and only one copy will ever be asked about"
        )
        assert (
            db_session.query(MemoryTransition).filter_by(run_id=run.id).count() == 2
        )

    def test_three_copies_against_one_row_adds_two(self, db_session, mid_run):
        project, _agent, run, path = mid_run
        line = "- a green run and a recorded run differ\n"
        path.write_text("## Verification\n" + line * 3, encoding="utf-8")
        assert memory_sweep.sweep(db_session, project, run).added_count == 2

    def test_one_agents_copies_do_not_cover_anothers(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """THE CASE THAT DISCRIMINATES (agent, excerpt) FROM excerpt alone.

        An earlier version of this class asserted two agents holding the same
        lesson both get rows, and a mutation keying the diff by excerpt alone
        PASSED it: the counts happened to work out, because the totals matched
        and the fresh rows arrived in agent order.

        They only diverge when the DISTRIBUTION across agents changes while the
        total does not. Here agent A held the lesson twice and has since
        condensed it away entirely, and agent B has written it twice. Keyed by
        excerpt alone, A's two stale rows cover B's two new ones and B's lessons
        are never enumerated at all.
        """
        project_dict = make_project(repo_path=str(tmp_path))
        a = make_agent(project_id=project_dict["id"], name="Alpha")
        b = make_agent(project_id=project_dict["id"], name="Beta")
        line = "- a green run and a recorded run differ\n"

        # Alpha holds it twice; Beta holds nothing.
        _write(tmp_path, project_dict["prefix"], "Alpha", "## Verification\n" + line * 2)
        _write(tmp_path, project_dict["prefix"], "Beta", "")
        project = db_session.get(Project, project_dict["id"])
        run = MemoryTransitionRun(
            project_id=project.id,
            direction=TransitionDirection.adopt,
            state=TransitionRunState.open,
            enumerated_at=datetime.now(timezone.utc),
        )
        db_session.add(run)
        db_session.flush()
        assert memory_adopt.enumerate_for_run(db_session, project=project, run=run) == 2

        # Alpha condenses it away; Beta writes it twice. Total unchanged at 2.
        _write(tmp_path, project_dict["prefix"], "Alpha", "## Verification\n")
        _write(tmp_path, project_dict["prefix"], "Beta", "## Verification\n" + line * 2)

        result = memory_sweep.sweep(db_session, project, run)

        assert result.added_count == 2, (
            "Beta's lessons were never enumerated: Alpha's stale rows covered "
            "them because the diff is keyed by excerpt rather than by "
            "(agent, excerpt)"
        )
        assert {r.agent_id for r in result.added} == {b["id"]}

    def test_two_agents_with_the_same_lesson_both_get_rows(
        self, db_session, make_project, make_agent, tmp_path
    ):
        """Keyed by (agent, excerpt), not by excerpt alone. Collapsing them
        would leave the second agent's copy unenumerated forever."""
        project_dict = make_project(repo_path=str(tmp_path))
        make_agent(project_id=project_dict["id"], name="First")
        make_agent(project_id=project_dict["id"], name="Second")
        _write(tmp_path, project_dict["prefix"], "First", SNAPSHOT)
        _write(tmp_path, project_dict["prefix"], "Second", SNAPSHOT)
        project = db_session.get(Project, project_dict["id"])
        run = MemoryTransitionRun(
            project_id=project.id,
            direction=TransitionDirection.adopt,
            state=TransitionRunState.open,
            enumerated_at=datetime.now(timezone.utc),
        )
        db_session.add(run)
        db_session.flush()

        assert memory_adopt.enumerate_for_run(db_session, project=project, run=run) == 2
        assert memory_sweep.sweep(db_session, project, run).is_empty


class TestCondenseMidRun:
    def test_a_rewritten_file_adds_the_rewrite_and_keeps_the_old_row(
        self, db_session, mid_run
    ):
        """An agent that condenses mid-run rewrites its file, so snapshot
        excerpts can vanish from it. Those rows STAY - they record a question
        that was asked - and the replacements arrive as new candidates."""
        project, _agent, run, path = mid_run
        original = db_session.query(MemoryTransition).filter_by(run_id=run.id).one()

        path.write_text(
            "## Verification\n- a green run and a RECORDED run are different facts\n",
            encoding="utf-8",
        )
        result = memory_sweep.sweep(db_session, project, run)

        assert result.added_count == 1
        assert db_session.get(MemoryTransition, original.id) is not None, (
            "the sweep removed a row whose excerpt left the file; the audit "
            "trail must keep questions that were asked"
        )


class TestDryRunAndBoundaries:
    def test_a_dry_run_writes_nothing(self, db_session, mid_run):
        project, _agent, run, path = mid_run
        path.write_text(SNAPSHOT + "- late\n", encoding="utf-8")
        before = db_session.query(MemoryTransition).filter_by(run_id=run.id).count()

        result = memory_sweep.sweep(db_session, project, run, persist=False)
        db_session.flush()

        assert result.added_count == 1
        assert (
            db_session.query(MemoryTransition).filter_by(run_id=run.id).count()
            == before
        )

    def test_a_sweep_does_not_touch_the_run(self, db_session, mid_run):
        """A sweep is not a new enumeration; it is the same one catching up.
        `enumerated_at` and the run's state belong to DWB-593's edges."""
        project, _agent, run, path = mid_run
        stamped = run.enumerated_at
        path.write_text(SNAPSHOT + "- late\n", encoding="utf-8")

        memory_sweep.sweep(db_session, project, run)

        assert run.enumerated_at == stamped
        assert run.state == TransitionRunState.open

    def test_an_unreadable_file_is_surfaced_rather_than_swallowed(
        self, db_session, mid_run
    ):
        """Same reason the snapshot surfaces it: unreadable and empty look
        identical downstream and only one of them is safe to sweep past."""
        import os

        project, _agent, run, path = mid_run
        os.chmod(path, 0o000)
        try:
            if os.geteuid() == 0:  # pragma: no cover
                pytest.skip("running as root; chmod 000 does not deny access")
            result = memory_sweep.sweep(db_session, project, run)
        finally:
            os.chmod(path, 0o644)

        assert result.is_defective
        assert result.unreadable, result.unreadable
