# Path: tests/test_memory_evict_dwb607.py
# File: test_memory_evict_dwb607.py
# Created: 2026-09-30 (DWB-607)
# Purpose: Guard WORKING-floor eviction - a memory at the floor is journaled
#          with its ORIGINAL date intact and its agent_memories row deleted,
#          journal-before-delete is observed rather than inferred, nothing
#          below the floor or outside WORKING is touched, and the write does
#          not inherit DWB-603's disputed scar-firing side effect.
# Caller: pytest
# Callees: app.services.memory_evict, app.services.memory_score
# Data In: factory agents/projects, agent_memories + dwb_session/hook_session
#          rows built the same way test_memory_score_dwb585.py's own fixtures
#          drive the decay curve
# Data Out: Assertions on the created journal entry, on deletion, and on order
# Last Modified: 2026-09-30 (DWB-611: scar_context_bound removed from the
#                non-WORKING-tier parametrization, one fewer tier value exists)

"""DWB-607 acceptance: "a WORKING memory at the floor is moved into the
journal with its original date intact and its AgentMemory row deleted."

Reuses the exact session-elapsing helpers `test_memory_score_dwb585.py` uses
to drive a memory to the floor, rather than writing a second way to fake
decay - two implementations of "N sessions have passed" is how this project's
own tests have drifted from each other before.

`TestOrderingIsObserved` mirrors `test_memory_revert_dwb595.py`'s own
technique for the same reason it exists there: asserting the journal row and
the deletion both happened AFTERWARDS passes for either order, which is
exactly the mistake DWB-594's skip path made once already. Watching state AT
the moment of the destructive step is the only proof that survives that
mistake.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import memory_evict as svc


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
        session_id=f"dwb607-{tag}", agent_id=agent_id, project_id=project_id,
        dwb_session_id=dwb_session_id, total_tokens=0,
    )
    db.add(h)
    db.flush()
    return h


def _elapse(db, *, project_id, agent_id, n):
    """N further closed sessions, each linked by a hook session - the same
    shape test_memory_score_dwb585.py uses to advance the decay clock."""
    for i in range(n):
        s = _closed_session(db, project_id, hours_ago=n - i)
        _hook_session(db, agent_id=agent_id, project_id=project_id, dwb_session_id=s.id, tag=f"e{i}")


def _memory(db, *, agent_id, tier=MemoryTier.working, **kw):
    kw.setdefault("body", "a lesson")
    row = AgentMemory(agent_id=agent_id, tier=tier, **kw)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


class TestAtTheFloorIsEvicted:
    def test_working_memory_at_the_floor_is_journaled_and_deleted(
        self, db_session, agent
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        original_date = datetime.now(timezone.utc) - timedelta(days=21)
        memory = _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            created_at=original_date, body="a fact nobody reinforced",
        )
        memory_id = memory.id
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)  # score 1

        created = svc.evict_working_memories(db_session, agent_id=agent_id)

        assert len(created) == 1
        entry = created[0]
        assert entry.body == "a fact nobody reinforced"
        assert entry.created_at.replace(tzinfo=timezone.utc) - original_date < timedelta(
            seconds=2
        ), "the journal entry must carry the memory's ORIGINAL date"
        now = datetime.now(timezone.utc)
        assert (now - entry.entered_at.replace(tzinfo=timezone.utc)) < timedelta(seconds=5), (
            "entered_at is when eviction happened, not the memory's original date"
        )
        assert entry.created_at != entry.entered_at

        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id) is None

    def test_eviction_tags_are_recorded(self, db_session, agent):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        created = svc.evict_working_memories(db_session, agent_id=agent_id)

        assert created[0].tags == svc.EVICTION_TAGS


class TestNotAtTheFloorIsUntouched:
    def test_a_demotion_band_memory_is_not_evicted(self, db_session, agent):
        """Band 2-4 (demote), not band 1 (evict) - the floor is a specific
        band, not "old"."""
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=15)  # score 4

        created = svc.evict_working_memories(db_session, agent_id=agent_id)

        assert created == []
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory.id) is not None

    def test_a_fresh_memory_is_nowhere_near_the_floor(self, db_session, agent):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1)
        _memory(db_session, agent_id=agent_id, created_session_id=origin.id)

        assert svc.evict_working_memories(db_session, agent_id=agent_id) == []

    def test_no_session_origin_is_excluded_same_as_scored_memory(
        self, db_session, agent
    ):
        """A row with neither created_session_id nor last_reinforced_session_id
        is reported UNSCORED by scored_memory(), never a candidate for
        anything. This consumer must agree, or it would evict a row
        scored_memory()'s own evict list would never have nominated."""
        agent_id = agent["id"]
        _memory(db_session, agent_id=agent_id)  # no session origin at all

        assert svc.evict_working_memories(db_session, agent_id=agent_id) == []


class TestOnlyWorkingTierIsEvicted:
    @pytest.mark.parametrize(
        "tier", [MemoryTier.scar, MemoryTier.core, MemoryTier.raw]
    )
    def test_non_working_tiers_are_never_evicted(self, db_session, agent, tier):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(db_session, agent_id=agent_id, tier=tier, created_session_id=origin.id)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        assert svc.evict_working_memories(db_session, agent_id=agent_id) == []
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory.id) is not None


class TestOrderingIsObserved:
    """The ticket's real requirement: journal BEFORE delete, proven at the
    instant the delete happens, not inferred from the end state."""

    def test_the_journal_row_exists_at_the_moment_of_delete(
        self, db_session, agent, monkeypatch
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        before = db_session.query(JournalEntry).count()
        seen = {}
        real_delete = db_session.delete

        def watched_delete(instance, *a, **k):
            seen["journal_rows"] = db_session.query(JournalEntry).count()
            return real_delete(instance, *a, **k)

        monkeypatch.setattr(db_session, "delete", watched_delete)
        svc.evict_working_memories(db_session, agent_id=agent_id)
        monkeypatch.undo()

        assert "journal_rows" in seen, "the memory was never deleted"
        assert seen["journal_rows"] == before + 1, (
            "the AgentMemory row was deleted before its journal entry was "
            "flushed; a failure there loses the content from both stores"
        )

    def test_a_failed_delete_leaves_the_journal_entry_already_flushed(
        self, db_session, agent, monkeypatch
    ):
        """The invariant the ordering buys: if the delete fails, the content
        is not lost - it is already sitting in the journal."""
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            body="must survive a failed delete",
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        def refuse(*_a, **_k):
            raise RuntimeError("delete unavailable")

        monkeypatch.setattr(db_session, "delete", refuse)
        with pytest.raises(RuntimeError):
            svc.evict_working_memories(db_session, agent_id=agent_id)
        monkeypatch.undo()

        journaled = (
            db_session.query(JournalEntry)
            .filter(JournalEntry.body == "must survive a failed delete")
            .one_or_none()
        )
        assert journaled is not None, "the journal write did not survive the failed delete"


class TestScoping:
    def test_scoped_to_the_given_agent(self, db_session, agent, make_agent):
        other = make_agent(project_id=agent["project_id"])
        origin = _closed_session(db_session, agent["project_id"], hours_ago=1000)
        _memory(db_session, agent_id=other["id"], created_session_id=origin.id)
        _elapse(
            db_session, project_id=agent["project_id"], agent_id=other["id"], n=91
        )

        assert svc.evict_working_memories(db_session, agent_id=agent["id"]) == []

    def test_no_agent_id_scopes_to_everyone(self, db_session, agent, make_agent):
        other = make_agent(project_id=agent["project_id"])
        origin = _closed_session(db_session, agent["project_id"], hours_ago=1000)
        _memory(db_session, agent_id=other["id"], created_session_id=origin.id)
        _elapse(
            db_session, project_id=agent["project_id"], agent_id=other["id"], n=91
        )

        created = svc.evict_working_memories(db_session)

        assert len(created) == 1
        assert created[0].agent_id == other["id"]
