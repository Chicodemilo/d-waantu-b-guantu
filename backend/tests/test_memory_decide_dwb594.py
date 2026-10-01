# Path: tests/test_memory_decide_dwb594.py
# File: test_memory_decide_dwb594.py
# Created: 2026-09-30 (DWB-594)
# Purpose: Guard the decide phase - one entry at a time and structurally no way
#          to get the file, CORE refused, and every skip journaled BEFORE the
#          state moves.
# Caller: pytest
# Callees: app.services.memory_decide
# Data In: lat_test rows
# Data Out: assertions
# Last Modified: 2026-09-30 (DWB-594)

"""DWB-594 phase 2.

Two tests carry the weight.

`TestCannotHandOverTheFile` is acceptance 2, asserted over the module's public
surface rather than by inspection. A `list_entries` helper added later for
convenience is exactly how this constraint gets lost, because it would look like
an improvement.

`TestJournalBeforeSkip` is the TL ruling of 2026-09-30, and the ordering test is
the one that matters: a skip whose journal write lands AFTER the state change
loses the entry if anything fails between them, and 595's revert then overwrites
the intact file with a version excluding it.
"""

import inspect
from datetime import datetime, timezone

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.models.memory_transition import (
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import memory_decide, memory_format


def _entry_excerpt(body: str, chain=("Verification discipline",)) -> str:
    return memory_format.render(
        [memory_format.MemoryEntry(body=body, heading_path=chain)]
    )


@pytest.fixture
def adopting(db_session, make_project, make_agent):
    """A project mid-adopt with two pending candidates for one agent."""
    project_dict = make_project()
    agent = make_agent(project_id=project_dict["id"])
    project = db_session.get(Project, project_dict["id"])
    project.memory_mode = MemoryMode.adopting

    run = MemoryTransitionRun(
        project_id=project.id,
        direction=TransitionDirection.adopt,
        state=TransitionRunState.open,
        enumerated_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    db_session.flush()

    rows = []
    for body in ["a green run and a recorded run differ", "never live-test a write"]:
        row = MemoryTransition(
            project_id=project.id,
            agent_id=agent["id"],
            run_id=run.id,
            state=TransitionState.pending,
            source_excerpt=_entry_excerpt(body),
        )
        db_session.add(row)
        rows.append(row)
    db_session.flush()
    return project, agent, run, rows


class TestCannotHandOverTheFile:
    """DWB-594 acceptance 2, the constraint the whole lane exists to enforce."""

    def test_next_entry_returns_one_row_not_a_collection(self, db_session, adopting):
        _project, agent, _run, rows = adopting
        got = memory_decide.next_entry(db_session, agent_id=agent["id"])
        assert isinstance(got, MemoryTransition)
        assert got.id == rows[0].id

    def test_no_public_function_returns_a_collection_of_entries(self):
        """Asserted over the module's SURFACE, not by reading it.

        A convenience helper returning every candidate is how this gets lost: it
        would look like an improvement and it would hand back the giant context
        list Miles ruled out. Any new public function whose return type mentions
        a container of transitions fails here.
        """
        offenders = []
        for name, obj in vars(memory_decide).items():
            if name.startswith("_") or not inspect.isfunction(obj):
                continue
            if obj.__module__ != memory_decide.__name__:
                continue
            annotation = str(inspect.signature(obj).return_annotation)
            if "MemoryTransition" in annotation and (
                "list" in annotation or "Sequence" in annotation or "[" in annotation
            ):
                # tuple[MemoryTransition, MemoryMode | None] is one row plus a
                # result, not a collection; allow it explicitly by shape.
                if not annotation.startswith("tuple["):
                    offenders.append((name, annotation))
        assert offenders == [], (
            f"public function(s) returning a collection of candidates: {offenders}. "
            "The decide phase hands over ONE entry; a listing helper defeats it."
        )

    def test_progress_is_available_as_a_count_not_as_the_queue(
        self, db_session, adopting
    ):
        """A number cannot be pasted into a prompt. That is the whole reason
        `remaining_count` is shaped this way rather than returning the rows."""
        _project, agent, _run, _rows = adopting
        assert memory_decide.remaining_count(db_session, agent_id=agent["id"]) == 2
        annotation = inspect.signature(memory_decide.remaining_count).return_annotation
        assert annotation is int

    def test_entries_come_back_oldest_first(self, db_session, adopting):
        _project, agent, _run, rows = adopting
        first = memory_decide.next_entry(db_session, agent_id=agent["id"])
        memory_decide.decide(
            db_session, transition_id=first.id, tier="working", decided_by="test"
        )
        second = memory_decide.next_entry(db_session, agent_id=agent["id"])
        assert [first.id, second.id] == [rows[0].id, rows[1].id]

    def test_no_open_run_yields_nothing_rather_than_everything(
        self, db_session, adopting
    ):
        _project, agent, run, _rows = adopting
        run.state = TransitionRunState.completed
        db_session.flush()
        assert memory_decide.next_entry(db_session, agent_id=agent["id"]) is None
        assert memory_decide.remaining_count(db_session, agent_id=agent["id"]) == 0


class TestTierRules:
    def test_core_is_refused_and_names_the_alternative(self, db_session, adopting):
        """A refusal that withholds the next action gets worked around.

        "Pick SCAR and let recurrence promote it" is the ticket's own guidance
        and it is what the agent should do instead, so the 400 says it.
        """
        _project, agent, _run, rows = adopting
        with pytest.raises(memory_decide.DecideError) as exc:
            memory_decide.decide(
                db_session, transition_id=rows[0].id, tier="core", decided_by="test"
            )
        assert exc.value.code == "core_forbidden"
        assert "hard rule 5" in exc.value.detail
        assert "SCAR" in exc.value.detail
        assert "tier down" in exc.value.detail

    def test_raw_is_refused_as_the_absence_of_a_judgement(self, db_session, adopting):
        _project, agent, _run, rows = adopting
        with pytest.raises(memory_decide.DecideError) as exc:
            memory_decide.decide(
                db_session, transition_id=rows[0].id, tier="raw", decided_by="test"
            )
        assert exc.value.code == "tier_not_decidable"

    @pytest.mark.parametrize(
        "tier", sorted(t.value for t in memory_decide.DECIDABLE_TIERS)
    )
    def test_every_decidable_tier_writes_a_memory_row(
        self, db_session, make_project, make_agent, tier
    ):
        """Parametrized over the set itself, so a tier added to DECIDABLE_TIERS
        without a working write path surfaces immediately."""
        project_dict = make_project()
        agent = make_agent(project_id=project_dict["id"])
        project = db_session.get(Project, project_dict["id"])
        project.memory_mode = MemoryMode.adopting
        run = MemoryTransitionRun(
            project_id=project.id,
            direction=TransitionDirection.adopt,
            state=TransitionRunState.open,
            enumerated_at=datetime.now(timezone.utc),
        )
        db_session.add(run)
        db_session.flush()
        row = MemoryTransition(
            project_id=project.id,
            agent_id=agent["id"],
            run_id=run.id,
            state=TransitionState.pending,
            source_excerpt=_entry_excerpt("a lesson"),
        )
        db_session.add(row)
        db_session.flush()

        memory_decide.decide(
            db_session, transition_id=row.id, tier=tier, decided_by="test"
        )
        memory = db_session.get(AgentMemory, row.target_memory_id)
        assert memory is not None
        assert memory.tier == MemoryTier(tier)
        assert memory.body == "a lesson"
        assert row.state == TransitionState.written

    def test_context_key_is_set_when_a_heading_path_is_available(
        self, db_session, adopting
    ):
        """DWB-611: there is one scar decision now, not two - context_key is
        gated on whether a heading path was recovered from the excerpt, not
        on which of two tier values was chosen (that second value no longer
        exists). Both rows are decided `scar`; only the heading differs."""
        _project, agent, run, rows = adopting
        # A candidate with no heading path at all, so this row's context_key
        # must come back None even though it is decided the same tier as the
        # bound one below.
        headless = MemoryTransition(
            project_id=rows[0].project_id,
            agent_id=agent["id"],
            run_id=run.id,
            state=TransitionState.pending,
            source_excerpt=_entry_excerpt("an unheaded lesson", chain=()),
        )
        db_session.add(headless)
        db_session.flush()

        memory_decide.decide(
            db_session, transition_id=rows[0].id, tier="scar", decided_by="test"
        )
        memory_decide.decide(
            db_session, transition_id=headless.id, tier="scar", decided_by="test"
        )
        bound = db_session.get(AgentMemory, rows[0].target_memory_id)
        plain = db_session.get(AgentMemory, headless.target_memory_id)
        assert bound.context_key == "Verification discipline"
        assert plain.context_key is None

    def test_deciding_twice_is_refused(self, db_session, adopting):
        _project, _agent, _run, rows = adopting
        memory_decide.decide(
            db_session, transition_id=rows[0].id, tier="working", decided_by="test"
        )
        with pytest.raises(memory_decide.DecideError) as exc:
            memory_decide.decide(
                db_session, transition_id=rows[0].id, tier="scar", decided_by="test"
            )
        assert exc.value.code == "already_decided"


class TestJournalBeforeSkip:
    """TL ruling 2026-09-30. A skip looks recoverable and is not.

    595's revert RENDERS THE STORE OVER THE FILE, and a skipped entry has no row
    in the store, so the revert overwrites the intact original with a version
    excluding exactly the content it was supposed to recover. The recovery path
    is the deletion.
    """

    def test_a_skip_writes_a_journal_entry(self, db_session, adopting):
        _project, agent, _run, rows = adopting
        before = db_session.query(JournalEntry).count()
        memory_decide.skip(db_session, transition_id=rows[0].id, decided_by="test")
        after = db_session.query(JournalEntry).count()
        assert after == before + 1

    def test_the_journal_entry_carries_the_content_and_its_heading(
        self, db_session, adopting
    ):
        _project, _agent, _run, rows = adopting
        memory_decide.skip(db_session, transition_id=rows[0].id, decided_by="test")
        entry = db_session.query(JournalEntry).order_by(JournalEntry.id.desc()).first()
        assert "a green run and a recorded run differ" in entry.body
        assert "Verification discipline" in entry.body
        assert entry.tags == memory_decide.SKIP_TAGS

    def test_a_failed_journal_write_leaves_the_row_UNDECIDED(
        self, db_session, adopting, monkeypatch
    ):
        """THE INVARIANT THAT ACTUALLY MATTERS: no skip without a journal entry.

        An earlier version of this test failed the journal and the state change
        apart and asserted on the in-memory row. That was wrong twice over:
        Python attribute assignment happens before any flush, so the object
        reads as skipped even when the write never reached the database, and
        inside one transaction both steps land or neither does anyway - so the
        transaction, not the ordering, is what stops a partial write.

        What ordering genuinely buys is this: if the journal cannot be written,
        the skip must not proceed. Asserted by making the journal write itself
        fail.
        """
        _project, _agent, _run, rows = adopting
        original_state = rows[0].state

        def refuse_journal(*_args, **_kwargs):
            raise RuntimeError("journal unavailable")

        monkeypatch.setattr(memory_decide, "JournalEntry", refuse_journal)
        with pytest.raises(RuntimeError):
            memory_decide.skip(db_session, transition_id=rows[0].id, decided_by="test")
        monkeypatch.undo()

        assert rows[0].state == original_state, (
            "the row was marked skipped even though the journal write failed; "
            "the content would be lost and 595's revert would then overwrite "
            "the intact file with a version excluding it"
        )
        assert rows[0].state not in (TransitionState.skipped,)

    def test_the_journal_row_exists_at_the_moment_the_state_changes(
        self, db_session, adopting
    ):
        """The ordering, observed rather than inferred.

        Reads the database at the instant the state assignment happens and
        asserts the journal entry is already there. Asserting both exist
        afterwards would pass for either order.
        """
        _project, _agent, _run, rows = adopting
        seen = {}

        from sqlalchemy import event

        target = rows[0]

        def on_set(_target, value, _oldvalue, _initiator):
            if value == TransitionState.skipped:
                seen["journal_rows"] = db_session.query(JournalEntry).count()
            return value

        event.listen(MemoryTransition.state, "set", on_set, retval=True)
        try:
            before = db_session.query(JournalEntry).count()
            memory_decide.skip(db_session, transition_id=target.id, decided_by="test")
        finally:
            event.remove(MemoryTransition.state, "set", on_set)

        assert "journal_rows" in seen, "the state was never set to skipped"
        assert seen["journal_rows"] == before + 1, (
            "the state moved to skipped while the journal entry did not yet "
            "exist; journal first, then rewrite"
        )

    def test_a_skip_writes_no_memory_row(self, db_session, adopting):
        _project, _agent, _run, rows = adopting
        before = db_session.query(AgentMemory).count()
        memory_decide.skip(db_session, transition_id=rows[0].id, decided_by="test")
        assert db_session.query(AgentMemory).count() == before
        assert rows[0].target_memory_id is None

    def test_a_reason_rides_along_when_given(self, db_session, adopting):
        _project, _agent, _run, rows = adopting
        memory_decide.skip(
            db_session,
            transition_id=rows[0].id,
            decided_by="test",
            reason="duplicate of an earlier note",
        )
        entry = db_session.query(JournalEntry).order_by(JournalEntry.id.desc()).first()
        assert "duplicate of an earlier note" in entry.body


class TestCutoverFiresOnTheLastDecision:
    def test_the_last_decision_lands_the_project(self, db_session, adopting):
        project, _agent, run, rows = adopting
        _row, landed = memory_decide.decide_and_maybe_cut_over(
            db_session, transition_id=rows[0].id, tier="working", decided_by="test"
        )
        assert landed is None, "cut over with a candidate still pending"

        _row, landed = memory_decide.decide_and_maybe_cut_over(
            db_session, transition_id=rows[1].id, tier="scar", decided_by="test"
        )
        assert landed == MemoryMode.human_memory
        assert project.memory_mode == MemoryMode.human_memory
        assert run.state == TransitionRunState.completed

    def test_a_skip_also_counts_toward_the_cutover(self, db_session, adopting):
        project, _agent, _run, rows = adopting
        memory_decide.decide_and_maybe_cut_over(
            db_session, transition_id=rows[0].id, tier="working", decided_by="test"
        )
        _row, landed = memory_decide.decide_and_maybe_cut_over(
            db_session, transition_id=rows[1].id, tier=None, decided_by="test"
        )
        assert landed == MemoryMode.human_memory
        assert project.memory_mode == MemoryMode.human_memory

    def test_all_skipped_does_not_cut_over(self, db_session, adopting):
        """The guard from the cutover module, reached through the real path.

        Every entry journaled and none written means the store is empty, and
        landing there would seal the flat file against nothing.
        """
        from app.services import memory_cutover

        project, _agent, _run, rows = adopting
        memory_decide.decide_and_maybe_cut_over(
            db_session, transition_id=rows[0].id, tier=None, decided_by="test"
        )
        with pytest.raises(memory_cutover.CutoverRefused):
            memory_decide.decide_and_maybe_cut_over(
                db_session, transition_id=rows[1].id, tier=None, decided_by="test"
            )
        assert project.memory_mode == MemoryMode.adopting


class TestExcerptRecovery:
    def test_an_unreadable_excerpt_refuses_rather_than_guessing(
        self, db_session, adopting
    ):
        """The excerpt is stored as a rendered entry and relies on render/split
        being exact inverses. If one is not, writing the raw text would smuggle
        heading markup into a lesson and dropping it would lose the entry."""
        _project, _agent, _run, rows = adopting
        rows[0].source_excerpt = ""
        db_session.flush()
        with pytest.raises(memory_decide.DecideError) as exc:
            memory_decide.decide(
                db_session, transition_id=rows[0].id, tier="working", decided_by="test"
            )
        assert exc.value.code == "excerpt_unreadable"
