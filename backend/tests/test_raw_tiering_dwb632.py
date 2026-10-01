# Path: tests/test_raw_tiering_dwb632.py
# File: test_raw_tiering_dwb632.py
# Created: 2026-10-01 (DWB-632)
# Purpose: Guard the missing section 4 mechanism - consolidation tiers RAW rows
#          from the moment-tags, defaulting DOWN to `working`, and never leaves
#          a tiered row unscoreable. Covers the delete-then-consolidate
#          sequence that the ticket was originally filed about.
# Caller: pytest
# Callees: app.services.memory_consolidate.tier_for_raw / tier_raw_memories /
#          consolidate_agent, app.services.memory_score, app.services.project
# Data In: factory projects/agents, agent_memories rows, dwb_sessions
# Data Out: Assertions on the STORED tier, origin and derived scoreability
# Last Modified: 2026-10-01 (DWB-632)

"""DWB-632 acceptance.

THE DEFECT WAS A MISSING MECHANISM, NOT A DESIGN CHOICE. Spec section 4 rules
that an agent appends RAW and unsorted during a session, because "tiering in
the moment rubber-stamps in-the-moment salience, which is the judgment
CONSOLIDATION exists to make", and the accepted amendment moves consolidation
to STARTUP because a session that dies badly never runs its shutdown.

Consolidation ran at startup and did four movements. None of them looked at
`raw`. Nothing anywhere in `app/` moved a row out of `raw`, so it was terminal
in practice: 39 rows of one evening's lessons sat permanently unscoreable,
excluded from every candidate list and never rendered, while `raw_memory.py`
told the agent consolidation would tier them later.

WHY `working` IS THE DEFAULT AND WHY THAT IS THE SAFETY MECHANISM. Defaulting
to `scar` would make an untagged scratch note consultable, which increments
`fired_count`, which at SCAR_FIRED_THRESHOLD promotes it to CORE - the tier
that never decays. An unjudged note would become a permanent memory with no
judgment by anyone. `working` is outside `SCAR_FAMILY`, so that path is
STRUCTURALLY unreachable rather than guarded. `TestAnUnjudgedRowCannotReachCore`
is the test that pins it.

ON ACCEPTANCE 3. The criterion asks for a test that goes red against today's
code by walking delete-then-consolidate and asserting the row is scoreable at
the end. `TestTheSequenceWalk` is exactly that walk and it fails against the
pre-DWB-632 code for TWO independent reasons, which is worth stating because
either alone would have made it red: consolidation never tiered the row, and
the delete had already removed its only origin. No substitution was needed.
"""

from datetime import datetime, timedelta

import pytest

from app.models.agent_memory import (
    AgentMemory,
    MemoryCaughtBy,
    MemoryCost,
    MemoryTier,
)
from app.models.dwb_session import DwbOpenMethod, DwbSession
from app.models.journal_entry import JournalEntry
from app.models.project import MemoryMode, Project
from app.services import memory_consolidate, memory_scan, memory_score


def _raw(db, agent_id, *, body="a lesson", cost=None, caught_by=None,
         surprised=None, created_session_id=None):
    row = AgentMemory(
        agent_id=agent_id,
        tier=MemoryTier.raw,
        body=body,
        cost=cost,
        caught_by=caught_by,
        surprised=surprised,
        created_session_id=created_session_id,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def agent_with_session(db_session, make_project, make_agent, tmp_path):
    """An agent on a human_memory project with an OPEN DWB session, which is
    the state consolidation actually runs in at session start."""
    project_dict = make_project(repo_path=str(tmp_path))
    agent = make_agent(project_id=project_dict["id"])
    project = db_session.get(Project, project_dict["id"])
    project.memory_mode = MemoryMode.human_memory
    session = DwbSession(
        project_id=project.id,
        opened_at=datetime(2026, 10, 1, 9, 0, 0),
        closed_at=None,
        open_method=DwbOpenMethod.slash,
    )
    db_session.add(session)
    db_session.flush()
    return project, agent, session


def _reread(db, memory_id):
    db.expire_all()
    return db.get(AgentMemory, memory_id)


class TestTheTieringRule:
    """The pure function, across every tag shape. No database."""

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"cost": MemoryCost.high}, MemoryTier.scar),
            ({"surprised": True}, MemoryTier.scar),
            ({"caught_by": MemoryCaughtBy.human}, MemoryTier.scar),
            ({"caught_by": MemoryCaughtBy.ci}, MemoryTier.scar),
            ({"caught_by": MemoryCaughtBy.worker}, MemoryTier.scar),
            # Self-caught is not a gap in the agent's own checks.
            ({"caught_by": MemoryCaughtBy.me}, MemoryTier.working),
            ({"cost": MemoryCost.low}, MemoryTier.working),
            ({"cost": MemoryCost.none}, MemoryTier.working),
            ({"surprised": False}, MemoryTier.working),
            # The case that matters most: nothing known about the moment.
            ({}, MemoryTier.working),
        ],
    )
    def test_the_tags_decide(self, kwargs, expected):
        row = AgentMemory(agent_id=1, tier=MemoryTier.raw, body="x", **kwargs)
        assert memory_consolidate.tier_for_raw(row) is expected

    def test_an_untagged_row_defaults_down_not_up(self):
        """Down from UNKNOWN is `working`. The adoption rule pointed at `scar`
        only because the alternative there was `core`."""
        row = AgentMemory(agent_id=1, tier=MemoryTier.raw, body="x")
        assert memory_consolidate.tier_for_raw(row) is MemoryTier.working

    def test_the_rule_reads_only_the_moment_tags(self):
        """Section 4 says tag only what the moment knows and cannot later be
        reconstructed. Two rows with identical tags and wildly different bodies
        must tier identically: judging the BODY would be judging salience from
        text, by a mechanism with no reader in the loop."""
        a = AgentMemory(agent_id=1, tier=MemoryTier.raw, body="trivial note")
        b = AgentMemory(
            agent_id=1, tier=MemoryTier.raw,
            body="CATASTROPHIC OUTAGE, EVERYTHING BURNED, NEVER AGAIN",
        )
        assert memory_consolidate.tier_for_raw(a) is memory_consolidate.tier_for_raw(b)


class TestAnUnjudgedRowCannotReachCore:
    """The reason `working` is the default, pinned structurally."""

    def test_working_is_outside_the_scar_family(self):
        assert MemoryTier.working not in memory_scan.SCAR_FAMILY
        assert MemoryTier.scar in memory_scan.SCAR_FAMILY

    def test_an_untagged_row_lands_outside_the_promotable_set(self):
        """`consult_scars` filters on SCAR_FAMILY, so a row outside it never
        increments fired_count, so `maybe_promote_scar` can never see it reach
        the threshold. The default does this; there is no guard to maintain."""
        row = AgentMemory(agent_id=1, tier=MemoryTier.raw, body="x")
        assert memory_consolidate.tier_for_raw(row) not in memory_scan.SCAR_FAMILY


class TestTieringMakesRowsScoreable:
    """The whole point: a tiered row is a VISIBLE row."""

    def test_a_raw_row_is_unscoreable_before_and_scoreable_after(
        self, db_session, agent_with_session
    ):
        _project, agent, session = agent_with_session
        row = _raw(
            db_session, agent["id"], cost=MemoryCost.high,
            created_session_id=session.id,
        )

        before = memory_score.scored_memory(db_session, agent_id=agent["id"])
        entry = next(e for e in before["entries"] if e["id"] == row.id)
        assert entry["scored"] is False
        assert entry["reason"] == memory_score.UNSCORED_UNTIERED

        memory_consolidate.tier_raw_memories(db_session, agent_id=agent["id"])

        after = memory_score.scored_memory(db_session, agent_id=agent["id"])
        entry = next(e for e in after["entries"] if e["id"] == row.id)
        assert entry["scored"] is True, "tiering must make the row scoreable"
        assert entry["tier"] == MemoryTier.scar.value

    def test_consolidate_agent_runs_it(self, db_session, agent_with_session):
        """Through the real entry point, not the helper."""
        _project, agent, session = agent_with_session
        row = _raw(db_session, agent["id"], created_session_id=session.id)

        result = memory_consolidate.consolidate_agent(db_session, agent_id=agent["id"])

        assert (row.id, MemoryTier.working.value) in result.tiered_raw
        assert result.moved_anything is True
        assert _reread(db_session, row.id).tier is MemoryTier.working


class TestTheSequenceWalk:
    """ACCEPTANCE 1 and 3, as an ORDERED PAIR rather than two assertions.

    Both halves pass alone: a delete leaves a raw row intact, and consolidation
    tiers a row that has an origin. The ticket is about what the SEQUENCE does,
    and it fails against pre-DWB-632 code for two independent reasons - nothing
    tiered the row, and the delete had removed its only origin.
    """

    def test_origin_destroyed_then_consolidated_leaves_a_scoreable_row(
        self, db_session, agent_with_session
    ):
        _project, agent, session = agent_with_session
        row = _raw(
            db_session, agent["id"], cost=MemoryCost.high,
            created_session_id=session.id,
        )

        # The delete teardown's effect on a raw row: both origins cleared, and
        # deliberately NOT journaled, because journaling pre-judgment content
        # contradicts what `raw` means. Reproduced directly rather than by
        # deleting a project, so this test is about the SEQUENCE and not about
        # project.delete_project's own behaviour.
        row.created_session_id = None
        row.last_reinforced_session_id = None
        db_session.flush()
        assert memory_score.sessions_since_reinforced(db_session, row) is None

        memory_consolidate.consolidate_agent(db_session, agent_id=agent["id"])

        after = _reread(db_session, row.id)
        assert after.tier is not MemoryTier.raw, "the row was never tiered"
        assert after.created_session_id is not None, (
            "tiered but origin-less: swapping one permanently invisible state "
            "for another"
        )
        scored = memory_score.scored_memory(db_session, agent_id=agent["id"])
        entry = next(e for e in scored["entries"] if e["id"] == row.id)
        assert entry["scored"] is True, (
            "the ordered pair delete-then-consolidate must not leave a tiered "
            "row unscoreable; this is the criterion the ticket names"
        )

    def test_a_row_with_a_surviving_origin_keeps_it(
        self, db_session, agent_with_session
    ):
        """ACCEPTANCE 4, the other side: tiering must not RESET a clock that is
        already running, or every raw row would arrive looking brand new."""
        _project, agent, session = agent_with_session
        older = DwbSession(
            project_id=_project.id,
            opened_at=datetime(2026, 9, 1, 9, 0, 0),
            closed_at=datetime(2026, 9, 1, 10, 0, 0),
            open_method=DwbOpenMethod.slash,
        )
        db_session.add(older)
        db_session.flush()
        row = _raw(db_session, agent["id"], created_session_id=older.id)

        memory_consolidate.tier_raw_memories(db_session, agent_id=agent["id"])

        assert _reread(db_session, row.id).created_session_id == older.id


class TestNothingPreJudgmentIsJournaled:
    """ACCEPTANCE 2."""

    def test_tiering_writes_no_journal_entry(self, db_session, agent_with_session):
        _project, agent, session = agent_with_session
        _raw(db_session, agent["id"], created_session_id=session.id)
        before = db_session.query(JournalEntry).count()

        memory_consolidate.tier_raw_memories(db_session, agent_id=agent["id"])

        assert db_session.query(JournalEntry).count() == before, (
            "raw content is pre-judgment; journaling it contradicts what raw "
            "means, which is why the delete path declined to"
        )


class TestTheStayRawFallback:
    """A row only leaves `raw` when it will be scoreable once it gets there."""

    def test_an_origin_less_row_stays_raw_when_no_session_is_open(
        self, db_session, agent_with_session
    ):
        _project, agent, session = agent_with_session
        session.closed_at = datetime(2026, 10, 1, 9, 30, 0)
        db_session.flush()
        row = _raw(db_session, agent["id"])  # no origin at all

        moved = memory_consolidate.tier_raw_memories(db_session, agent_id=agent["id"])

        assert moved == []
        assert _reread(db_session, row.id).tier is MemoryTier.raw, (
            "tiering it here would strand it: a raw row can wait for the next "
            "pass, a tiered origin-less row is stuck forever because nothing "
            "looks at it again"
        )


class TestOrdering:
    """Tiering runs LAST, so a row judged in this pass is not also evicted in
    it."""

    def test_a_row_tiered_this_pass_is_not_evicted_this_pass(
        self, db_session, agent_with_session
    ):
        """An old raw note becomes `working` already at its decay floor. If
        tiering ran before the eviction step, it would be journaled and deleted
        in the same pass - journaled first, so nothing is LOST, but the lesson
        would go from written to gone without ever being visible to anyone.
        """
        _project, agent, session = agent_with_session
        old = DwbSession(
            project_id=_project.id,
            opened_at=datetime(2025, 1, 1, 9, 0, 0),
            closed_at=datetime(2025, 1, 1, 10, 0, 0),
            open_method=DwbOpenMethod.slash,
        )
        db_session.add(old)
        db_session.flush()
        row = _raw(db_session, agent["id"], created_session_id=old.id)

        memory_consolidate.consolidate_agent(db_session, agent_id=agent["id"])

        survivor = _reread(db_session, row.id)
        assert survivor is not None, "tiered and evicted in one pass"
        assert survivor.tier is MemoryTier.working
