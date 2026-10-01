# Path: tests/test_memory_scar_conclude_dwb609.py
# File: test_memory_scar_conclude_dwb609.py
# Created: 2026-09-30 (DWB-609)
# Purpose: Guard the fifth movement - a resting (score 6) scar whose context
#          has concluded is journaled with its ORIGINAL date intact and its
#          agent_memories row deleted; journal-before-delete is observed
#          rather than inferred; a scar not yet at rest, or whose context is
#          still active or cannot die, is untouched.
# Caller: pytest
# Callees: app.services.memory_scar_conclude, app.services.memory_scan
# Data In: factory agents/projects/tickets, agent_memories + dwb_session/
#          hook_session rows driving the decay curve
# Data Out: Assertions on the created journal entry, on deletion, on order
# Last Modified: 2026-09-30 (DWB-609)

"""DWB-609's absorbed consumer, acceptance mirrored from DWB-607's own
(`test_memory_evict_dwb607.py`) since the shape is identical - journal
before delete, original date preserved, idempotent by construction - and
only the TRIGGER differs: a SCAN result instead of a score/band computation.

Reuses the session-elapsing helpers verbatim from test_memory_evict_dwb607.py
and test_memory_score_dwb585.py rather than writing a third copy; this is the
third test file to need "N sessions have passed" and the fourth would be the
one to actually extract a shared fixture, but that is not this ticket's call
to make unilaterally in files three other people's tickets own.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import memory_scar_conclude as svc


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
        session_id=f"dwb609-conclude-{tag}", agent_id=agent_id, project_id=project_id,
        dwb_session_id=dwb_session_id, total_tokens=0,
    )
    db.add(h)
    db.flush()
    return h


def _elapse(db, *, project_id, agent_id, n):
    for i in range(n):
        s = _closed_session(db, project_id, hours_ago=n - i)
        _hook_session(db, agent_id=agent_id, project_id=project_id, dwb_session_id=s.id, tag=f"e{i}")


def _memory(db, *, agent_id, tier=MemoryTier.scar, **kw):
    kw.setdefault("body", "a lesson")
    row = AgentMemory(agent_id=agent_id, tier=tier, **kw)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


class TestRestingAndConcludedIsEvicted:
    def test_a_resting_scar_tied_to_a_done_ticket_is_journaled_and_deleted(
        self, db_session, agent, make_ticket
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(
            project_id=project_id, ticket_key="DWB-1801", status="done",
            title="Shipped lane",
        )
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        original_date = datetime.now(timezone.utc) - timedelta(days=40)
        memory = _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            created_at=original_date, body="scar about the shipped lane",
            context_key=f"{ticket['ticket_key']} / notes",
        )
        memory_id = memory.id
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)  # score 6, resting

        created = svc.evict_concluded_scars(db_session, agent_id=agent_id)

        assert len(created) == 1
        entry = created[0]
        assert entry.body == "scar about the shipped lane"
        assert entry.created_at.replace(tzinfo=timezone.utc) - original_date < timedelta(
            seconds=2
        ), "the journal entry must carry the memory's ORIGINAL date"
        now = datetime.now(timezone.utc)
        assert (now - entry.entered_at.replace(tzinfo=timezone.utc)) < timedelta(seconds=5)
        assert entry.created_at != entry.entered_at

        db_session.expire_all()
        assert db_session.get(AgentMemory, memory_id) is None

    def test_concluded_tags_are_recorded(self, db_session, agent, make_ticket):
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(project_id=project_id, ticket_key="DWB-1802", status="done")
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            context_key=f"{ticket['ticket_key']} / notes",
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        created = svc.evict_concluded_scars(db_session, agent_id=agent_id)
        assert created[0].tags == svc.CONCLUDED_TAGS


class TestUntouchedCases:
    def test_resting_but_context_still_active_is_untouched(
        self, db_session, agent, make_ticket
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(project_id=project_id, ticket_key="DWB-1803", status="in_progress")
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            context_key=f"{ticket['ticket_key']} / notes",
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        assert svc.evict_concluded_scars(db_session, agent_id=agent_id) == []
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory.id) is not None

    def test_resting_but_cannot_die_is_untouched(self, db_session, agent):
        """cannot_die is DWB-606's trigger (promote to CORE), not this
        movement's - a context naming nothing trackable must not be
        journaled by this consumer."""
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            context_key="general coding-standards lesson",
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        assert svc.evict_concluded_scars(db_session, agent_id=agent_id) == []
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory.id) is not None

    def test_resting_but_no_context_key_is_untouched(self, db_session, agent):
        """DWB-611 sequencing ruling: no context_key means still_active, not
        finished and not cannot_die."""
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(db_session, agent_id=agent_id, created_session_id=origin.id)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        assert svc.evict_concluded_scars(db_session, agent_id=agent_id) == []
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory.id) is not None

    def test_not_yet_resting_is_untouched_even_with_a_done_ticket(
        self, db_session, agent, make_ticket
    ):
        """Spec section 2: 'entries sitting at 6 get periodically
        re-examined.' A scar still climbing toward 6 (gap=10 -> score 8) is
        not a candidate yet, regardless of what its context resolves to."""
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(project_id=project_id, ticket_key="DWB-1804", status="done")
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            context_key=f"{ticket['ticket_key']} / notes",
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=10)  # score 8

        assert svc.evict_concluded_scars(db_session, agent_id=agent_id) == []
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory.id) is not None

    @pytest.mark.parametrize("tier", [MemoryTier.core, MemoryTier.working, MemoryTier.raw])
    def test_non_scar_tiers_are_never_touched(self, db_session, agent, tier):
        agent_id, project_id = agent["id"], agent["project_id"]
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        memory = _memory(db_session, agent_id=agent_id, tier=tier, created_session_id=origin.id)
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        assert svc.evict_concluded_scars(db_session, agent_id=agent_id) == []
        db_session.expire_all()
        assert db_session.get(AgentMemory, memory.id) is not None

    def test_no_session_origin_is_excluded(self, db_session, agent):
        agent_id = agent["id"]
        _memory(db_session, agent_id=agent_id)  # no session origin at all
        assert svc.evict_concluded_scars(db_session, agent_id=agent_id) == []


class TestOrderingIsObserved:
    """Same requirement, same proof technique, as DWB-607's own ordering
    test: journal BEFORE delete, watched at the instant the delete happens."""

    def test_the_journal_row_exists_at_the_moment_of_delete(
        self, db_session, agent, make_ticket, monkeypatch
    ):
        agent_id, project_id = agent["id"], agent["project_id"]
        ticket = make_ticket(project_id=project_id, ticket_key="DWB-1805", status="done")
        origin = _closed_session(db_session, project_id, hours_ago=1000)
        _memory(
            db_session, agent_id=agent_id, created_session_id=origin.id,
            context_key=f"{ticket['ticket_key']} / notes",
        )
        _elapse(db_session, project_id=project_id, agent_id=agent_id, n=91)

        before = db_session.query(JournalEntry).count()
        seen = {}
        real_delete = db_session.delete

        def watched_delete(instance, *a, **k):
            seen["journal_rows"] = db_session.query(JournalEntry).count()
            return real_delete(instance, *a, **k)

        monkeypatch.setattr(db_session, "delete", watched_delete)
        svc.evict_concluded_scars(db_session, agent_id=agent_id)
        monkeypatch.undo()

        assert "journal_rows" in seen, "the memory was never deleted"
        assert seen["journal_rows"] == before + 1


class TestScoping:
    def test_scoped_to_the_given_agent(self, db_session, agent, make_agent, make_ticket):
        other = make_agent(project_id=agent["project_id"])
        ticket = make_ticket(project_id=agent["project_id"], ticket_key="DWB-1806", status="done")
        origin = _closed_session(db_session, agent["project_id"], hours_ago=1000)
        _memory(
            db_session, agent_id=other["id"], created_session_id=origin.id,
            context_key=f"{ticket['ticket_key']} / notes",
        )
        _elapse(db_session, project_id=agent["project_id"], agent_id=other["id"], n=91)

        assert svc.evict_concluded_scars(db_session, agent_id=agent["id"]) == []

    def test_no_agent_id_scopes_to_everyone(self, db_session, agent, make_agent, make_ticket):
        other = make_agent(project_id=agent["project_id"])
        ticket = make_ticket(project_id=agent["project_id"], ticket_key="DWB-1807", status="done")
        origin = _closed_session(db_session, agent["project_id"], hours_ago=1000)
        _memory(
            db_session, agent_id=other["id"], created_session_id=origin.id,
            context_key=f"{ticket['ticket_key']} / notes",
        )
        _elapse(db_session, project_id=agent["project_id"], agent_id=other["id"], n=91)

        assert len(svc.evict_concluded_scars(db_session, agent_id=None)) == 1
