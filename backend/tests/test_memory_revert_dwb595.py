# Path: tests/test_memory_revert_dwb595.py
# File: test_memory_revert_dwb595.py
# Created: 2026-09-30 (DWB-595)
# Purpose: Guard the revert - under the ceiling, ordered by tier then score,
#          everything dropped journaled BEFORE it leaves, and the journal
#          itself untouched.
# Caller: pytest
# Callees: app.services.memory_revert
# Data In: lat_test rows plus a tmp_path repo
# Data Out: assertions
# Last Modified: 2026-10-01 (DWB-617: store size derived from the ceiling constant)

"""DWB-595.

AC2's ordering test is the one that carries the ticket: "written BEFORE the
drop. A test proves the ordering by asserting the journal row exists at the
moment the drop is attempted." Asserting both happened afterwards passes for
either order, which is the mistake I already made once in DWB-594's skip path.

AC3 is the other half and it is an ABSENCE: the journal is neither deleted nor
modified. Compared row by row including `retrieval_count`, because a revert that
reset those counts would silently destroy the promotion signal while looking
like it preserved everything.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.token_budget import ceiling_for_file, estimate_tokens
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.models.project import MemoryMode, Project
from app.services import memory_format, memory_revert

CEILING = ceiling_for_file("memory.md")


def _add_memory(db_session, agent_id, body, tier=MemoryTier.working):
    row = AgentMemory(agent_id=agent_id, tier=tier, body=body)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def reverting(db_session, make_project, make_agent, tmp_path):
    project_dict = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project_dict["id"], name="Reverter")
    project = db_session.get(Project, project_dict["id"])
    project.memory_mode = MemoryMode.reverting
    db_session.flush()
    return project, agent


class TestRenderOrderAndCeiling:
    """AC1: at or under the ceiling, ordered by tier then score."""

    def test_tiers_render_in_order(self, db_session, reverting):
        project, agent = reverting
        _add_memory(db_session, agent["id"], "a working note", MemoryTier.working)
        _add_memory(db_session, agent["id"], "a core ruling", MemoryTier.core)
        _add_memory(db_session, agent["id"], "a scar", MemoryTier.scar)

        text = memory_revert.plan(db_session, project).agents[0].rendered
        assert text.index("CORE") < text.index("SCAR") < text.index("WORKING")
        assert text.index("a core ruling") < text.index("a scar")
        assert text.index("a scar") < text.index("a working note")

    def test_the_output_is_at_or_under_the_ceiling(self, db_session, reverting):
        project, agent = reverting
        # Comfortably over the ceiling on its own, sized FROM the constant so a
        # raise (DWB-617 took memory_main 4500 -> 12000) cannot quietly leave
        # this store UNDER it, which would exercise no drop at all. Each entry
        # is ~192 chars, so ~48 tokens; the dropped_count assertion below is the
        # loud backstop if that arithmetic ever drifts.
        for i in range((CEILING * 2) // 48):
            _add_memory(db_session, agent["id"], f"lesson number {i} " * 12)

        agent_revert = memory_revert.plan(db_session, project).agents[0]
        assert estimate_tokens(agent_revert.rendered) <= CEILING
        assert agent_revert.dropped_count > 0, "nothing was dropped; ceiling untested"

    def test_a_small_store_drops_nothing(self, db_session, reverting):
        """The positive that keeps the ceiling tests honest: dropping is not
        something this does unconditionally."""
        project, agent = reverting
        _add_memory(db_session, agent["id"], "one short lesson")
        agent_revert = memory_revert.plan(db_session, project).agents[0]
        assert agent_revert.dropped == []
        assert "one short lesson" in agent_revert.rendered

    def test_the_lowest_scoring_entries_are_the_ones_dropped(
        self, db_session, reverting
    ):
        """CORE never fades and WORKING decays fastest, so under pressure the
        working notes go and the core rulings stay."""
        project, agent = reverting
        # Entry count derived from the ceiling (~120 tokens each) so the store
        # stays over it when the cap moves; dropped_count below is the backstop.
        for i in range((CEILING * 2) // 120):
            _add_memory(db_session, agent["id"], f"working {i} " * 40, MemoryTier.working)
        core = _add_memory(db_session, agent["id"], "the core ruling", MemoryTier.core)

        agent_revert = memory_revert.plan(db_session, project).agents[0]
        assert agent_revert.dropped_count > 0
        assert core.id in [m.id for m in agent_revert.kept]
        assert core.id not in [m.id for m in agent_revert.dropped]

    def test_the_render_round_trips_through_the_shared_format(
        self, db_session, reverting
    ):
        """The file this writes is the file an adopt will later split. Using the
        shared module for both is what stops the two disagreeing."""
        project, agent = reverting
        _add_memory(db_session, agent["id"], "a lesson worth keeping", MemoryTier.scar)

        text = memory_revert.plan(db_session, project).agents[0].rendered
        entries = memory_format.split(text).entries
        assert [e.body for e in entries] == ["a lesson worth keeping"]
        assert entries[0].heading_path == ("SCAR",)

    def test_the_plan_is_deterministic(self, db_session, reverting):
        project, agent = reverting
        for i in range(30):
            _add_memory(db_session, agent["id"], f"lesson {i}")
        first = memory_revert.plan(db_session, project).agents[0]
        second = memory_revert.plan(db_session, project).agents[0]
        assert first.rendered == second.rendered
        assert [m.id for m in first.dropped] == [m.id for m in second.dropped]


class TestJournalBeforeDrop:
    """AC2. The ordering is the ticket, not a nicety."""

    def test_everything_dropped_is_in_the_journal(self, db_session, reverting):
        project, agent = reverting
        for i in range(400):
            _add_memory(db_session, agent["id"], f"lesson number {i} " * 12)

        result = memory_revert.execute(db_session, project)
        dropped_bodies = {m.body for m in result.agents[0].dropped}
        assert dropped_bodies, "nothing was dropped; the assertion below is vacuous"

        journalled = {
            e.body
            for e in db_session.query(JournalEntry)
            .filter(JournalEntry.agent_id == agent["id"])
            .all()
        }
        assert dropped_bodies <= journalled, (
            f"{len(dropped_bodies - journalled)} dropped memories were not "
            "journaled; that content is gone from both stores"
        )

    def test_the_journal_rows_exist_at_the_moment_the_file_is_written(
        self, db_session, reverting, monkeypatch
    ):
        """AC2's ordering, observed rather than inferred.

        Reads the journal at the instant the file write happens. Asserting both
        afterwards would pass for either order - the mistake I made once already
        on DWB-594's skip path.
        """
        project, agent = reverting
        for i in range(400):
            _add_memory(db_session, agent["id"], f"lesson number {i} " * 12)

        before = db_session.query(JournalEntry).count()
        seen = {}
        real_write = Path.write_text

        def watched_write(self, *args, **kwargs):
            seen["journal_rows"] = db_session.query(JournalEntry).count()
            return real_write(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", watched_write)
        result = memory_revert.execute(db_session, project)
        monkeypatch.undo()

        assert "journal_rows" in seen, "no file was written"
        assert seen["journal_rows"] == before + result.agents[0].dropped_count, (
            "the flat file was written before the dropped memories were "
            "journaled; a failure there loses them from both stores"
        )

    def test_a_failed_journal_write_leaves_the_file_untouched(
        self, db_session, reverting, monkeypatch
    ):
        """The invariant the ordering buys: if the journal cannot be written,
        the file must not be rewritten without that content."""
        project, agent = reverting
        for i in range(400):
            _add_memory(db_session, agent["id"], f"lesson number {i} " * 12)
        path = memory_revert.plan(db_session, project).agents[0].path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ORIGINAL CONTENT\n", encoding="utf-8")

        def refuse(*_a, **_k):
            raise RuntimeError("journal unavailable")

        monkeypatch.setattr(memory_revert, "JournalEntry", refuse)
        with pytest.raises(RuntimeError):
            memory_revert.execute(db_session, project)
        monkeypatch.undo()

        assert path.read_text(encoding="utf-8") == "ORIGINAL CONTENT\n"

    def test_dropped_entries_are_tagged_so_they_can_be_found(
        self, db_session, reverting
    ):
        project, agent = reverting
        for i in range(400):
            _add_memory(db_session, agent["id"], f"lesson number {i} " * 12)
        memory_revert.execute(db_session, project)
        entry = (
            db_session.query(JournalEntry)
            .filter(JournalEntry.agent_id == agent["id"])
            .first()
        )
        assert entry.tags == memory_revert.JOURNAL_TAGS_DROPPED


class TestTheJournalSurvivesFrozen:
    """AC3 and AC4. Ruled by Miles: not deleted, not flattened into the file."""

    def _snapshot(self, db_session):
        return sorted(
            (e.id, e.body, e.retrieval_count, tuple(e.tags or []))
            for e in db_session.query(JournalEntry).all()
        )

    def test_existing_journal_rows_are_identical_after_a_revert(
        self, db_session, reverting
    ):
        project, agent = reverting
        pre = JournalEntry(
            agent_id=agent["id"],
            tags=["earlier"],
            body="an episode from before the revert",
            retrieval_count=2,
        )
        db_session.add(pre)
        db_session.flush()
        _add_memory(db_session, agent["id"], "a lesson")
        before = self._snapshot(db_session)

        memory_revert.execute(db_session, project)
        db_session.expire_all()
        after = self._snapshot(db_session)

        assert before, "no journal rows existed; this check saw nothing"
        # Every pre-existing row survives byte for byte, including its count.
        assert set(before) <= set(after), (
            "a revert modified or deleted an existing journal row"
        )

    def test_retrieval_counts_are_not_reset(self, db_session, reverting):
        """The count is the promotion signal. A revert that reset it would look
        like it preserved everything while destroying why an entry mattered."""
        project, agent = reverting
        pre = JournalEntry(
            agent_id=agent["id"], tags=["x"], body="reached for often", retrieval_count=7
        )
        db_session.add(pre)
        db_session.flush()
        _add_memory(db_session, agent["id"], "a lesson")

        memory_revert.execute(db_session, project)
        db_session.expire_all()
        assert db_session.get(JournalEntry, pre.id).retrieval_count == 7

    def test_the_journal_is_not_flattened_into_the_file(self, db_session, reverting):
        """Section 5: memory must shrink and the journal may sprawl. Pouring the
        sprawling store into the shrinking one is the one combination guaranteed
        to fail."""
        project, agent = reverting
        db_session.add(
            JournalEntry(
                agent_id=agent["id"],
                tags=["x"],
                body="JOURNAL CONTENT THAT MUST NOT REACH THE FILE",
            )
        )
        db_session.flush()
        _add_memory(db_session, agent["id"], "a real lesson")

        result = memory_revert.execute(db_session, project)
        text = result.agents[0].path.read_text(encoding="utf-8")
        assert "a real lesson" in text
        assert "MUST NOT REACH THE FILE" not in text

    def test_a_re_adopt_after_a_revert_finds_the_journal_intact(
        self, db_session, reverting
    ):
        """AC4. What makes revert a reversible decision rather than a
        destructive one."""
        project, agent = reverting
        for i in range(400):
            _add_memory(db_session, agent["id"], f"lesson number {i} " * 12)

        result = memory_revert.execute(db_session, project)
        dropped = result.agents[0].dropped_count
        assert dropped > 0

        project.memory_mode = MemoryMode.stock
        db_session.flush()
        db_session.expire_all()

        surviving = (
            db_session.query(JournalEntry)
            .filter(JournalEntry.agent_id == agent["id"])
            .count()
        )
        assert surviving == dropped, (
            "the journal did not survive the revert intact, so a re-adopt "
            "cannot get the dropped content back"
        )


class TestBoundaries:
    def test_plan_writes_nothing(self, db_session, reverting):
        """Asserts the file is UNCHANGED, not that it is absent.

        The first version asserted `not path.exists()` and failed: agent
        creation scaffolds the memory dir with an empty memory.md, so the file
        was already there before plan() was ever called. The assertion never
        established its own precondition - the same shape as an absence check
        that passes because it saw nothing, inverted.
        """
        project, agent = reverting
        _add_memory(db_session, agent["id"], "a lesson")
        before_journal = db_session.query(JournalEntry).count()
        path = memory_revert.plan(db_session, project).agents[0].path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRE-EXISTING CONTENT\n", encoding="utf-8")
        before_bytes = path.read_bytes()

        result = memory_revert.plan(db_session, project)

        assert result.agents[0].rendered, "plan produced nothing to compare against"
        assert db_session.query(JournalEntry).count() == before_journal
        assert path.read_bytes() == before_bytes, (
            "plan() wrote to the flat file; only execute() may touch it"
        )

    def test_an_agent_with_no_memories_gets_an_empty_file_not_a_crash(
        self, db_session, reverting
    ):
        project, _agent = reverting
        result = memory_revert.execute(db_session, project)
        assert result.agents[0].kept == []
        assert result.agents[0].path.exists()

    def test_raw_rows_render_last_and_are_dropped_first(self, db_session, reverting):
        """`memory_score.score` REFUSES raw, so the sort needs its own answer.
        Untiered rows are the ones no judgement was made about, which makes them
        the cheapest to lose."""
        project, agent = reverting
        _add_memory(db_session, agent["id"], "a scar lesson", MemoryTier.scar)
        _add_memory(db_session, agent["id"], "an unsorted note", MemoryTier.raw)

        agent_revert = memory_revert.plan(db_session, project).agents[0]
        text = agent_revert.rendered
        assert text.index("a scar lesson") < text.index("an unsorted note")
        assert agent_revert.kept[-1].tier == MemoryTier.raw
