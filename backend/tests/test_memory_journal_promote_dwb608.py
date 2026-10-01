# Path: tests/test_memory_journal_promote_dwb608.py
# File: test_memory_journal_promote_dwb608.py
# Created: 2026-09-30 (DWB-608)
# Purpose: Guard journal-to-core promotion - an entry at 3+ retrievals is
#          promoted through the DWB-606 shared helper, the journal entry
#          survives untouched, and a repeated consolidation run does not
#          mint a duplicate CORE memory for the same story.
# Caller: pytest
# Callees: app.services.memory_promote, app.services.journal
# Data In: factory agents/projects, journal_entries rows retrieved via the
#          real search path (not a fabricated retrieval_count)
# Data Out: Assertions on the created AgentMemory and on idempotence
# Last Modified: 2026-09-30 (DWB-608)

"""DWB-608 acceptance: "a journal entry with retrieval_count >= 3 is promoted
to an AgentMemory row with tier=core, proven by a test."

Every entry here reaches its retrieval count through `journal_svc.search_entries`
- the real retrieval path - rather than being constructed with the count
already set, for the same reason the audit that found this gap insisted on
proof against stored state rather than a code path's existence: a fabricated
count would prove the CONSUMER works without proving it agrees with what the
PRODUCER (DWB-587's journal) actually counts.

`TestIdempotence` is the ticket's harder half. journal.py's own rule is that
`retrieval_count` never decays, so an entry that crosses the threshold once
stays a candidate on every later call to `journal.promotion_candidates()`
forever. A naive consumer re-promotes it every time it runs; the module
docstring names `source_journal_id` as the guard, and this is where that
guard gets proved rather than asserted.
"""

import pytest

from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import journal as journal_svc
from app.services import memory_promote as svc

THRESHOLD = journal_svc.PROMOTION_THRESHOLD


@pytest.fixture
def agent(make_project, make_agent):
    project = make_project()
    return make_agent(project_id=project["id"])


def _retrieve_n_times(db, *, agent_id, tag, n):
    for _ in range(n):
        journal_svc.search_entries(db, agent_id=agent_id, tags=[tag])


class TestPromotionAtThreshold:
    def test_entry_at_threshold_is_promoted(self, db_session, agent):
        entry = journal_svc.create_entry(
            db_session, agent_id=agent["id"], body="a lesson worth keeping",
            tags=["probe608"],
        )
        _retrieve_n_times(db_session, agent_id=agent["id"], tag="probe608", n=THRESHOLD)
        assert entry.retrieval_count == THRESHOLD

        created = svc.promote_journal_candidates(db_session, agent_id=agent["id"])

        assert len(created) == 1
        assert created[0].tier == MemoryTier.core
        assert created[0].body == "a lesson worth keeping"
        assert created[0].source_journal_id == entry.id

    def test_entry_below_threshold_is_not_promoted(self, db_session, agent):
        journal_svc.create_entry(
            db_session, agent_id=agent["id"], body="not reached for enough yet",
            tags=["probe608b"],
        )
        _retrieve_n_times(
            db_session, agent_id=agent["id"], tag="probe608b", n=THRESHOLD - 1
        )

        created = svc.promote_journal_candidates(db_session, agent_id=agent["id"])

        assert created == []

    def test_no_journal_entries_at_all_returns_empty(self, db_session, agent):
        assert svc.promote_journal_candidates(db_session, agent_id=agent["id"]) == []


class TestTheJournalEntrySurvives:
    """DWB-608's documented decision: retained, never deleted."""

    def test_the_source_entry_still_exists_after_promotion(self, db_session, agent):
        entry = journal_svc.create_entry(
            db_session, agent_id=agent["id"], body="kept after promotion",
            tags=["probe608c"],
        )
        _retrieve_n_times(db_session, agent_id=agent["id"], tag="probe608c", n=THRESHOLD)

        svc.promote_journal_candidates(db_session, agent_id=agent["id"])

        db_session.expire_all()
        from app.models.journal_entry import JournalEntry

        still_there = db_session.get(JournalEntry, entry.id)
        assert still_there is not None
        assert still_there.body == "kept after promotion"


class TestIdempotence:
    """THE HARD HALF: retrieval_count never decays, so the same entry stays a
    candidate forever. A second consolidation pass must not re-promote it."""

    def test_calling_it_twice_does_not_duplicate(self, db_session, agent):
        entry = journal_svc.create_entry(
            db_session, agent_id=agent["id"], body="promote me once",
            tags=["probe608d"],
        )
        _retrieve_n_times(db_session, agent_id=agent["id"], tag="probe608d", n=THRESHOLD)

        first = svc.promote_journal_candidates(db_session, agent_id=agent["id"])
        assert len(first) == 1

        # A later session reads the journal again - the entry is STILL a
        # candidate (its count never decayed) but must not mint a second row.
        _retrieve_n_times(db_session, agent_id=agent["id"], tag="probe608d", n=1)
        second = svc.promote_journal_candidates(db_session, agent_id=agent["id"])

        assert second == []
        rows = (
            db_session.query(AgentMemory)
            .filter(AgentMemory.source_journal_id == entry.id)
            .all()
        )
        assert len(rows) == 1, f"expected exactly one promoted row, found {len(rows)}"


class TestScoping:
    def test_scoped_to_the_given_agent(self, db_session, agent, make_agent):
        other = make_agent(project_id=agent["project_id"])
        journal_svc.create_entry(
            db_session, agent_id=other["id"], body="someone elses lesson",
            tags=["probe608e"],
        )
        _retrieve_n_times(db_session, agent_id=other["id"], tag="probe608e", n=THRESHOLD)

        created = svc.promote_journal_candidates(db_session, agent_id=agent["id"])

        assert created == []

    def test_no_agent_id_scopes_to_everyone(self, db_session, agent, make_agent):
        other = make_agent(project_id=agent["project_id"])
        journal_svc.create_entry(
            db_session, agent_id=other["id"], body="also worth keeping",
            tags=["probe608f"],
        )
        _retrieve_n_times(db_session, agent_id=other["id"], tag="probe608f", n=THRESHOLD)

        created = svc.promote_journal_candidates(db_session)

        assert len(created) == 1
        assert created[0].agent_id == other["id"]
