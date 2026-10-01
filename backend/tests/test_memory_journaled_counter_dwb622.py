# Path: tests/test_memory_journaled_counter_dwb622.py
# File: test_memory_journaled_counter_dwb622.py
# Created: 2026-10-01 (DWB-622)
# Purpose: Guard the two halves of the skip/journal disagreement. (1) The
#          entries_journaled counter was fed by a state nothing ever sets, so
#          it was structurally incapable of returning a positive while journal
#          rows existed. (2) The cutover guard defined the preserving states as
#          {written, journaled}, excluding skipped on the false grounds that a
#          skip keeps nothing, so an all-skipped run could be refused with a
#          message that was the opposite of the truth.
# Caller: pytest
# Callees: app.services.memory_decide.skip, app.services.memory_cutover,
#          app.services.memory_transition.get_transition_status, ast
# Data In: factory projects/agents, memory_transition runs and rows
# Data Out: Assertions on the status counters, on the cutover outcome, and on
#           which TransitionState members have a writer in app/
# Last Modified: 2026-10-01 (DWB-622)

"""DWB-622 acceptance.

THE SHAPE, AND IT IS THE ONE THIS LANE KEEPS PRODUCING: a check that cannot
produce the positive it is read as producing. `entries_journaled` counted
`TransitionState.journaled`. Nothing in app/ has ever set that state. So the
field did not report zero because nothing was journaled; it reported zero
because the state it counted was unreachable, while six journal_entries rows
sat in production saying otherwise.

THE SECOND BUG IS THE DANGEROUS ONE and it is not the counter. `memory_cutover`
excluded `skipped` from its preserving set with a comment stating a skip keeps
nothing. DWB-594's own ruling had already made every skip journal the entry
FIRST, flushed before the row goes terminal, precisely because an unjournaled
skip is the one unrecoverable loss in the design. So the two halves of one lane
disagreed about what `skipped` means.

WHAT THE FIX IS NOT, because this is the trap and the first attempt here fell
into it. The obvious response is "skipped preserves, so let the all-skipped run
cut over". That REMOVES the protection. The guard's question is not whether the
entry was preserved; it is whether anything landed in the NEW STORE. The
journal is never auto-loaded, so a run whose entries all went there leaves the
agent carrying nothing and unable to read the file the cutover sealed - exactly
the harm the module docstring describes.

The evidence that settles it, and it was already in the suite:
`test_all_skipped_does_not_cut_over` drives the REAL skip path, so its entries
ARE journaled, and its docstring reads "Every entry journaled and none written
means the store is empty". DWB-594 knew skips journal and still wanted the
refusal. So the refusal stays; what changed is the message, which asserted
nothing had been journaled while the journal held every entry.

WHAT WAS CHOSEN, PER ACCEPTANCE 1. The counter stops claiming to count
something unreachable. `written` and `skipped` partition the terminal rows;
`entries_journaled` became an OVERLAY over that partition counting rows whose
content reached the journal - every skip, plus any legacy `journaled` row. It
overlaps `skipped` deliberately and must not be summed alongside it.

The alternative, making `skip()` set `journaled`, was rejected on evidence
rather than taste: production holds 396 written, 6 skipped and 0 journaled, and
`skipped` is the state the decide path, the abort wind-back and the existing
rows all speak. Moving skips onto `journaled` would have zeroed
`entries_skipped` instead, which is the same bug with the names exchanged.
"""

import ast
import pathlib
from datetime import datetime

import pytest

from app.models.journal_entry import JournalEntry
from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import memory_cutover, memory_decide, memory_format
from app.services import memory_transition as status_svc

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


def _entry_excerpt(body: str, chain=("Verification discipline",)) -> str:
    return memory_format.render(
        [memory_format.MemoryEntry(body=body, heading_path=chain)]
    )


@pytest.fixture
def adopting(db_session, make_project, make_agent, tmp_path):
    """A project mid-adopt with three enumerated candidates for one agent.

    Flush rather than commit: conftest shares one session between `client` and
    `db_session`, so a commit here would end the harness's outer transaction
    and leak these rows past teardown.
    """
    project_dict = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project_dict["id"])
    project = db_session.get(Project, project_dict["id"])
    project.memory_mode = MemoryMode.adopting

    run = MemoryTransitionRun(
        project_id=project.id,
        direction=TransitionDirection.adopt,
        state=TransitionRunState.open,
        started_at=datetime(2026, 10, 1, 10, 0, 0),
        enumerated_at=datetime(2026, 10, 1, 10, 0, 5),
    )
    db_session.add(run)
    db_session.flush()

    rows = []
    for i in range(3):
        row = MemoryTransition(
            project_id=project.id,
            agent_id=agent["id"],
            run_id=run.id,
            state=TransitionState.pending,
            source_excerpt=_entry_excerpt(f"lesson number {i} that cost us time"),
        )
        db_session.add(row)
        rows.append(row)
    db_session.flush()
    return project, agent, run, rows


def _journal_rows(db, agent_id):
    return (
        db.query(JournalEntry).filter(JournalEntry.agent_id == agent_id).all()
    )


class TestTheCounterCanReturnAPositive:
    """ACCEPTANCE 1 and 4a. Fails against the pre-DWB-622 code, where
    entries_journaled was wired to an unreachable state."""

    def test_a_skip_is_counted_as_journaled(self, db_session, adopting):
        project, agent, run, rows = adopting
        memory_decide.skip(
            db_session, transition_id=rows[0].id, decided_by="Stan", reason="noise"
        )

        status = status_svc.get_transition_status(db_session, project.id)

        assert status.entries_skipped == 1
        assert status.entries_journaled == 1, (
            "a skip journals its content before going terminal, so the "
            "journaled counter must be able to see it"
        )

    def test_the_counter_reconciles_against_journal_entries(
        self, db_session, adopting
    ):
        """ACCEPTANCE 1, literally: an operator must be able to reconcile the
        counter against journal_entries without reading the code."""
        project, agent, run, rows = adopting
        for row in rows:
            memory_decide.skip(
                db_session, transition_id=row.id, decided_by="Stan", reason="noise"
            )

        status = status_svc.get_transition_status(db_session, project.id)
        journal_count = len(_journal_rows(db_session, agent["id"]))

        assert journal_count == 3
        assert status.entries_journaled == journal_count, (
            f"status says {status.entries_journaled} journaled, the journal "
            f"holds {journal_count} rows for this agent"
        )

    def test_written_and_skipped_still_partition_the_terminal_rows(
        self, db_session, adopting
    ):
        """The overlay must not break the partition. `journaled` is NOT a third
        bucket and must not be added into this sum."""
        project, agent, run, rows = adopting
        memory_decide.skip(
            db_session, transition_id=rows[0].id, decided_by="Stan", reason="noise"
        )
        rows[1].state = TransitionState.written
        db_session.flush()

        status = status_svc.get_transition_status(db_session, project.id)

        assert status.entries_total == 3
        assert status.entries_done == 2
        assert status.entries_written + status.entries_skipped == status.entries_done


class TestTheRefusalTellsTheTruth:
    """ACCEPTANCE 2 and 4b.

    The refusal itself is CORRECT and stays: an all-skipped run puts nothing in
    the new store, and the journal is never auto-loaded, so cutting over would
    leave the agent carrying nothing and unable to read the file it sealed.

    What was wrong was the message. It asserted that nothing had been journaled
    in precisely the case where everything had. An operator who checks that and
    finds the journal full has been given a reason to distrust the whole
    refusal, which is worse than a wrong number on a dashboard.
    """

    def test_an_all_skipped_run_is_not_told_nothing_was_journaled(
        self, db_session, adopting
    ):
        """ACCEPTANCE 2, and note what it does and does NOT require.

        It requires the refusal to stop REPORTING that nothing was journaled
        when journal rows exist. It does not require the cutover to proceed,
        and making it proceed would be wrong: the journal is never auto-loaded,
        so an all-skipped cutover seals the flat file and leaves the agent with
        nothing to carry and nothing to read. That is the exact harm the guard
        describes, so the guard is right to fire and was only ever wrong about
        what it said.
        """
        project, agent, run, rows = adopting
        for row in rows:
            memory_decide.skip(
                db_session, transition_id=row.id, decided_by="Stan", reason="noise"
            )
        # The precondition this test exists to measure against, asserted in the
        # test rather than assumed: the content really is in the journal.
        assert len(_journal_rows(db_session, agent["id"])) == 3

        with pytest.raises(memory_cutover.CutoverRefused) as caught:
            memory_cutover.complete_if_finished(db_session, project)

        message = str(caught.value)
        assert "nothing was journaled" not in message, message
        assert "skipped: 3" in message, (
            "the refusal must REPORT the states it measured, so an operator can "
            f"reconcile it against the journal: {message}"
        )
        assert "reached its destination" in message, message

    def test_the_preserving_set_was_confirmed_not_changed(self):
        """DWB-622 left `_PRESERVING_STATES` alone, and this pins why.

        The set is a union across both DIRECTIONS: `written` is how an adopt
        reaches its destination, `journaled` is how a revert reaches its.
        Adding `skipped` would let an all-skipped run seal the file against an
        empty store; removing `journaled` would refuse every legitimate revert.
        Both were attempted during this ticket and both were wrong.
        """
        assert memory_cutover._PRESERVING_STATES == frozenset(
            {TransitionState.written, TransitionState.journaled}
        )
        assert TransitionState.skipped not in memory_cutover._PRESERVING_STATES

    def test_abort_skipped_rows_can_never_reach_the_cutover(
        self, db_session, adopting
    ):
        """SCOPE PIN for the claim that a skipped row implies a journal row.

        It holds for `memory_decide.skip()` and NOT for the abort wind-back in
        project.py, which marks rows skipped without journaling. That second
        writer cannot reach the cutover or the status, because the same
        transaction sets the run to `aborted` and both resolve their run by
        `state == open`. If someone ever aborts without closing the run, this
        goes red and the implication above stops being safe.
        """
        import inspect

        from app.services import project as project_svc

        source = inspect.getsource(project_svc)
        assert "TransitionState.skipped" in source, (
            "the abort wind-back is the second writer of `skipped`; if it has "
            "moved, re-check that this scope argument still holds"
        )
        assert "TransitionRunState.aborted" in source, (
            "abort must close the run, or its unjournaled skipped rows become "
            "visible to the cutover guard and to the status counters"
        )


class TestTheOldDefinitionsProducedTheBug:
    """ACCEPTANCE 4, both bugs, each demonstrated SEPARATELY.

    The acceptance asks for a test that fails against the pre-fix code. The
    tests above do - but proving that by reverting the services would mean
    making a shared working tree deliberately wrong while other sessions are
    running the suite against it. So the mutation is applied to the module
    globals for the duration of one test instead, which is a mutation nobody
    else's process can observe.

    Each test here asserts the OLD definition reproduces the OLD symptom. If
    someone restores either old constant, these go red and say why.
    """

    def test_bug_one_the_counter_was_structurally_zero(
        self, db_session, adopting, monkeypatch
    ):
        project, agent, run, rows = adopting
        for row in rows:
            memory_decide.skip(
                db_session, transition_id=row.id, decided_by="Stan", reason="noise"
            )
        assert len(_journal_rows(db_session, agent["id"])) == 3

        monkeypatch.setattr(
            status_svc,
            "_JOURNALED_STATES",
            frozenset({TransitionState.journaled}),
        )
        status = status_svc.get_transition_status(db_session, project.id)

        assert status.entries_skipped == 3
        assert status.entries_journaled == 0, (
            "this is the defect being reproduced: three journal rows exist and "
            "the old counter reports zero, because it counted a state nothing "
            "sets"
        )

    def test_bug_two_the_refusal_asserted_nothing_was_journaled(
        self, db_session, adopting, monkeypatch
    ):
        """The second bug was the refusal's TEXT, not the refusal.

        Reproduced by restoring the old hard-coded message. The old wording
        told an operator that nothing was written and nothing was journaled,
        while three journal rows existed, and there was no measurement anywhere
        in it that could have disagreed.
        """
        project, agent, run, rows = adopting
        for row in rows:
            memory_decide.skip(
                db_session, transition_id=row.id, decided_by="Stan", reason="noise"
            )
        journal_rows = len(_journal_rows(db_session, agent["id"]))
        assert journal_rows == 3

        old_message = (
            "has 3 entries and every one was skipped, so nothing was "
            "written to the store and nothing was journaled."
        )
        # The claim the old text made, against the fact that was true at the
        # same moment. This is the whole defect in two lines.
        assert "nothing was journaled" in old_message
        assert journal_rows > 0

        # And the current text makes no such claim.
        with pytest.raises(memory_cutover.CutoverRefused) as caught:
            memory_cutover.complete_if_finished(db_session, project)
        assert "nothing was journaled" not in str(caught.value)


def _python_sources() -> list[pathlib.Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _states_set_in_app() -> set[str]:
    """Every TransitionState member that app/ actually ASSIGNS somewhere.

    Two shapes: `row.state = TransitionState.X` and `state=TransitionState.X`
    passed as a keyword. A member that appears only in a comparison, a set
    literal or a docstring is NOT reachable - being mentioned is not being
    written, and that difference is the whole of this ticket.
    """
    found: set[str] = set()

    def record(value) -> None:
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "TransitionState"
        ):
            found.add(value.attr)

    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Attribute) and t.attr == "state":
                        record(node.value)
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "state":
                        record(kw.value)
    return found


# Which TransitionState members each reported counter is derived from. This is
# the mapping the guard below checks, kept beside the test rather than imported
# so that changing the service forces someone to look at this list too.
REPORTING_FIELDS: dict[str, set[TransitionState]] = {
    "entries_written": {TransitionState.written},
    "entries_skipped": {TransitionState.skipped},
    "entries_journaled": set(status_svc._JOURNALED_STATES),
}


class TestNoReportingFieldCountsAnUnreachableState:
    """ACCEPTANCE 3. The criterion that prevents the NEXT instance rather than
    fixing this one."""

    def test_the_scan_can_see_states_being_assigned_at_all(self):
        """Positive control. A scanner whose pattern matches nothing reports
        every state unreachable and would fail this file for the wrong reason,
        or pass a different assertion vacuously."""
        assigned = _states_set_in_app()
        assert {"written", "skipped", "pending"} <= assigned, assigned

    def test_no_reporting_field_is_fed_only_by_states_nothing_sets(self):
        assigned = _states_set_in_app()
        for field, states in REPORTING_FIELDS.items():
            reachable = {s.value for s in states} & assigned
            assert reachable, (
                f"{field} is derived only from states that nothing in app/ "
                f"ever assigns: {sorted(s.value for s in states)}. It is "
                "structurally incapable of returning a positive, which is not "
                "the same fact as there being nothing to count."
            )

    def test_the_set_of_unreachable_states_is_exactly_what_we_think(self):
        """Pins the deliberate non-decisions.

        ONE state has no writer now. It was THREE when this was written:
        `proposed` and `decided` were found by this very assertion going red,
        and DWB-631 removed them from the enum entirely, because they described
        a two-phase flow section 4 rules out. `journaled` stays because a
        reporting field derives from it and the cutover guard holds a
        definition of it, so it has live consequences those two did not.

        Pinned so that giving `journaled` a writer, or adding a state nothing
        writes, forces a visit to this file.
        """
        unreachable = {s.value for s in TransitionState} - _states_set_in_app()
        assert unreachable == {"journaled"}, (
            "the unreachable-state set moved. If a writer for `journaled` was "
            "added, entries_journaled should go back to counting it alone and "
            "this pin should be updated. If a NEW state has no writer, it is "
            f"the next instance of DWB-631. Found: {sorted(unreachable)}"
        )
