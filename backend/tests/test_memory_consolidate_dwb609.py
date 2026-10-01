# Path: tests/test_memory_consolidate_dwb609.py
# File: test_memory_consolidate_dwb609.py
# Created: 2026-09-30 (DWB-609)
# Purpose: Guard the session-start consolidation orchestrator - all four
#          movements fire from one call when their conditions are seeded
#          together, the promotion-before-eviction order is observed on a
#          row that qualifies for both, and the job fires nothing (no
#          fired_count/retrieval_count write) regardless of what it moves.
# Caller: pytest
# Callees: app.services.memory_consolidate
# Data In: factory agents/projects/tickets, agent_memories/journal_entries
#          rows, dwb_session/hook_session rows driving the decay curve
# Data Out: Assertions on ConsolidationResult and on final row state
# Last Modified: 2026-09-30 (DWB-609)

"""DWB-609's own acceptance, verbatim: "on a fresh session start for an agent
in human_memory mode, a WORKING memory at the floor is evicted to the
journal, a scar meeting either core trigger is promoted, and a journal entry
at 3+ retrievals is promoted, all without any LLM decision in the loop,
proven end to end by a test that seeds all three conditions and asserts all
three movements fired from one job invocation." `TestAllMovementsFireTogether`
is that test, extended to the fourth movement this ticket absorbed (context-
concluded scar eviction) so all FIVE of Miles's movements are proven from one
call, not three.

`TestPromotionBeforeEviction` is the ordering requirement from the module
docstring, proven on a single row engineered to qualify for BOTH triggers at
once (fired_count>=3 AND a concluded context) rather than inferred from two
separate rows never interacting.

`TestFiresNothing` is the ruling itself, checked rather than assumed: run a
full consolidation pass seeded exactly like the acceptance test, then assert
fired_count on every surviving scar and retrieval_count on every surviving
journal entry are UNCHANGED from what they were seeded at. A pass that moved
four kinds of things could easily have also ticked a counter it was never
supposed to touch; this is the test that would catch it.
"""

from datetime import datetime, timedelta

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import memory_consolidate as svc


def _closed_session(db, project_id, *, hours_ago=1):
    from app.models.dwb_session import DwbCloseMethod, DwbOpenMethod, DwbSession

    s = DwbSession(
        project_id=project_id,
        opened_at=datetime.utcnow() - timedelta(hours=hours_ago),
        closed_at=datetime.utcnow() - timedelta(hours=hours_ago) + timedelta(minutes=5),
        open_method=DwbOpenMethod.regex,
        close_method=DwbCloseMethod.regex,
    )
    db.add(s)
    db.flush()
    return s


def _hook_session(db, *, agent_id, project_id, dwb_session_id, tag):
    from app.models.hook_session import HookSession

    h = HookSession(
        session_id=f"dwb609-consolidate-{tag}", agent_id=agent_id, project_id=project_id,
        dwb_session_id=dwb_session_id, total_tokens=0,
    )
    db.add(h)
    db.flush()
    return h


def _elapse(db, *, project_id, agent_id, n):
    for i in range(n):
        s = _closed_session(db, project_id, hours_ago=n - i)
        _hook_session(db, agent_id=agent_id, project_id=project_id, dwb_session_id=s.id, tag=f"e{i}")


def _memory(db, *, agent_id, tier, **kw):
    kw.setdefault("body", "a lesson")
    row = AgentMemory(agent_id=agent_id, tier=tier, **kw)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


class TestAllMovementsFireTogether:
    def test_one_call_fires_all_four_movements(
        self, db_session, agent, make_ticket
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=2000)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)
        # One shared, fully-elapsed clock: every row below is seeded off the
        # same `origin`, so each one's own session gap is 91 regardless of
        # which movement it is meant to trigger.

        # (a) WORKING at the floor.
        working = _memory(
            db_session, agent_id=agent_id, tier=MemoryTier.working,
            created_session_id=origin.id, body="a box fact at the floor",
        )

        # (b) SCAR fired 3x.
        fired_scar = _memory(
            db_session, agent_id=agent_id, tier=MemoryTier.scar,
            created_session_id=origin.id, fired_count=3,
            body="a scar that recurred",
        )

        # (c) SCAR context concluded.
        done_ticket = make_ticket(project_id=project_id, ticket_key="DWB-1901", status="done")
        concluded_scar = _memory(
            db_session, agent_id=agent_id, tier=MemoryTier.scar,
            created_session_id=origin.id,
            context_key=f"{done_ticket['ticket_key']} / notes",
            body="a scar whose context shipped",
        )

        # (d) SCAR context cannot die.
        durable_scar = _memory(
            db_session, agent_id=agent_id, tier=MemoryTier.scar,
            created_session_id=origin.id,
            context_key="general coding-standards lesson",
            body="a durable lesson",
        )

        # (e) JOURNAL entry at 3+ retrievals.
        journal_entry = JournalEntry(
            agent_id=agent_id, retrieval_count=3, body="a story reached for three times",
        )
        db_session.add(journal_entry)
        db_session.flush()

        result = svc.consolidate_agent(db_session, agent_id=agent_id)

        # (a)
        assert len(result.evicted_working) == 1
        assert result.evicted_working[0].body == "a box fact at the floor"

        # (b)
        assert (fired_scar.id, "fired_three_times") in result.promoted_scars

        # (c)
        assert len(result.concluded_scars) == 1
        assert result.concluded_scars[0].body == "a scar whose context shipped"

        # (d)
        assert (durable_scar.id, "context_cannot_die") in result.promoted_scars

        # (e)
        assert len(result.promoted_journal) == 1
        assert result.promoted_journal[0].source_journal_id == journal_entry.id

        db_session.expire_all()
        # WORKING and the concluded scar are gone from agent_memories, journaled.
        assert db_session.get(AgentMemory, working.id) is None
        assert db_session.get(AgentMemory, concluded_scar.id) is None
        # The two promoted scars survive, retiered to CORE in place.
        assert db_session.get(AgentMemory, fired_scar.id).tier == MemoryTier.core
        assert db_session.get(AgentMemory, durable_scar.id).tier == MemoryTier.core

        assert result.moved_anything is True

    def test_a_quiet_pass_moves_nothing(self, db_session, agent):
        """No seeded condition anywhere - the overwhelmingly common case, and
        it must not raise or nominate anything."""
        result = svc.consolidate_agent(db_session, agent_id=agent["id"])
        assert result.moved_anything is False
        assert result.promoted_scars == []
        assert result.concluded_scars == []
        assert result.evicted_working == []
        assert result.promoted_journal == []


class TestPromotionBeforeEviction:
    """The module docstring's real claim: a scar that qualifies for BOTH
    triggers in the same pass is promoted, not evicted - proven on one row
    engineered to satisfy both, not two rows that never interact."""

    def test_a_scar_satisfying_both_triggers_is_promoted_not_evicted(
        self, db_session, agent, make_ticket
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        done_ticket = make_ticket(project_id=project_id, ticket_key="DWB-1902", status="done")
        both = _memory(
            db_session, agent_id=agent_id, tier=MemoryTier.scar,
            created_session_id=origin.id, fired_count=3,
            context_key=f"{done_ticket['ticket_key']} / notes",
            body="fired three times AND its context just concluded",
        )

        result = svc.consolidate_agent(db_session, agent_id=agent_id)

        assert (both.id, "fired_three_times") in result.promoted_scars
        assert result.concluded_scars == []

        db_session.expire_all()
        promoted = db_session.get(AgentMemory, both.id)
        assert promoted is not None, "promotion must win: the row must still exist"
        assert promoted.tier == MemoryTier.core


class TestFiresNothing:
    """Miles's ruling, checked rather than assumed: a consolidation pass
    that moves four kinds of things must not tick fired_count or
    retrieval_count on anything it leaves behind."""

    def test_surviving_counters_are_unchanged_after_a_full_pass(
        self, db_session, agent, make_ticket
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        # A scar that survives the pass untouched: fired_count below
        # threshold, context tied to a still-OPEN ticket (still_active, ask
        # neither trigger). Its fired_count must read back exactly what it
        # was seeded at.
        open_ticket = make_ticket(project_id=project_id, ticket_key="DWB-1903", status="in_progress")
        surviving_scar = _memory(
            db_session, agent_id=agent_id, tier=MemoryTier.scar,
            created_session_id=origin.id, fired_count=1,
            context_key=f"{open_ticket['ticket_key']} / still open",
        )

        # A journal entry below the promotion threshold - must survive with
        # its count unchanged.
        surviving_journal = JournalEntry(
            agent_id=agent_id, retrieval_count=2, body="not yet promoted",
        )
        db_session.add(surviving_journal)
        db_session.flush()

        svc.consolidate_agent(db_session, agent_id=agent_id)

        db_session.expire_all()
        assert db_session.get(AgentMemory, surviving_scar.id).fired_count == 1
        assert db_session.get(JournalEntry, surviving_journal.id).retrieval_count == 2


class TestScoping:
    def test_scoped_to_the_given_agent(self, db_session, agent, make_agent):
        other = make_agent(project_id=agent["project_id"])
        origin = _closed_session(db_session, agent["project_id"], hours_ago=1000)
        _elapse(db_session, project_id=agent["project_id"], agent_id=other["id"], n=91)
        _memory(
            db_session, agent_id=other["id"], tier=MemoryTier.working,
            created_session_id=origin.id, body="someone else's floor memory",
        )

        result = svc.consolidate_agent(db_session, agent_id=agent["id"])
        assert result.moved_anything is False

        db_session.expire_all()
        others_memories = (
            db_session.query(AgentMemory).filter_by(agent_id=other["id"]).count()
        )
        assert others_memories == 1, "another agent's memory must not be touched"
