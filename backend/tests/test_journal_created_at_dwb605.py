# Path: tests/test_journal_created_at_dwb605.py
# File: test_journal_created_at_dwb605.py
# Created: 2026-09-30 (DWB-605)
# Purpose: Guard journal_entries.created_at - the memory's ORIGINAL date,
#          distinct from entered_at's journal-arrival date. Proves the
#          default (created_at == entered_at for an entry journaled directly)
#          and the DWB-607 contract (created_at carries the evicted memory's
#          own original date when a caller supplies one).
# Caller: pytest
# Callees: app.services.journal.create_entry, app.models.agent_memory
# Data In: factory fixtures, direct ORM rows via db_session
# Data Out: Assertions on both timestamp columns
# Last Modified: 2026-09-30 (DWB-605)

"""DWB-605 acceptance.

DWB-607 (WORKING-floor eviction, not yet built) is the actual call site that
will move a WORKING memory into the journal with a known original insert
date. This file cannot drive that path yet, so it proves the contract DWB-605
owns and DWB-607 will consume: `journal.create_entry` accepts an optional
`created_at` and, when given one, stores it distinct from `entered_at` -
which is exactly what "moves a WORKING memory with a known original insert
date into the journal and asserts both fields" reduces to at the layer that
exists today. Simulated here with a real AgentMemory row's own `created_at`,
not an arbitrary timestamp, so the test exercises the actual value DWB-607
will pass rather than a stand-in shaped like it.
"""

from datetime import datetime, timedelta, timezone

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import journal as journal_svc


class TestDefaultBehaviourUnchanged:
    """An entry journaled directly (every call site before DWB-607 exists)
    gets created_at == entered_at - zero behaviour change from before this
    column existed."""

    def test_created_at_defaults_to_entered_at_moment(self, client, make_agent, db_session):
        agent = make_agent()
        r = client.post(
            "/api/journal",
            json={"agent_id": agent["id"], "body": "an ordinary entry, no backdating"},
        )
        assert r.status_code == 201, r.text
        entry_id = r.json()["id"]

        db_session.expire_all()
        row = db_session.get(JournalEntry, entry_id)
        assert row.created_at is not None
        assert row.entered_at is not None
        # Same moment (server-side now() for both columns on the same INSERT),
        # not merely "both non-null".
        assert abs((row.created_at - row.entered_at).total_seconds()) < 2


class TestOriginalDateCarriedForward:
    """The DWB-607 contract: create_entry(created_at=...) stores the memory's
    ORIGINAL date distinctly from the journal-arrival date."""

    def test_moving_a_working_memory_preserves_its_original_date(
        self, make_agent, db_session
    ):
        agent = make_agent()

        # A WORKING memory "created" three weeks ago - the date DWB-607's
        # eviction will read off the row it is about to journal.
        original_date = datetime.now(timezone.utc) - timedelta(days=21)
        memory = AgentMemory(
            agent_id=agent["id"],
            tier=MemoryTier.working,
            body="a box fact nobody reinforced, now at the floor",
            created_at=original_date,
        )
        db_session.add(memory)
        db_session.commit()
        db_session.refresh(memory)
        assert memory.created_at.replace(tzinfo=timezone.utc) - original_date < timedelta(
            seconds=2
        )

        # DWB-607's move: journal the evicted memory's body, carrying its
        # original created_at forward. entered_at is NOT passed - it stamps
        # "now", the moment of eviction, which is correct: that is genuinely
        # when this entry arrived in the journal.
        entry = journal_svc.create_entry(
            db_session,
            agent_id=agent["id"],
            body=memory.body,
            created_at=memory.created_at,
        )
        db_session.commit()
        db_session.refresh(entry)

        assert entry.created_at == memory.created_at
        # The two dates genuinely differ - this is the failure DWB-605 exists
        # to prevent: entered_at alone would have overwritten the 21-day-old
        # original date with the eviction moment.
        now = datetime.now(timezone.utc)
        assert (now - entry.created_at.replace(tzinfo=timezone.utc)) > timedelta(days=20)
        assert (now - entry.entered_at.replace(tzinfo=timezone.utc)) < timedelta(seconds=5)
        assert entry.created_at != entry.entered_at

    def test_explicit_created_at_none_uses_the_column_default_not_a_null_insert(
        self, make_agent, db_session
    ):
        """Passing created_at=None (the default) must not attempt to insert a
        NULL - the model has no fallback for that, the column is NOT NULL.
        Guards the exact mistake the docstring in create_entry warns against:
        setting the attribute to None instead of leaving it unset."""
        agent = make_agent()
        entry = journal_svc.create_entry(
            db_session, agent_id=agent["id"], body="no created_at supplied"
        )
        db_session.commit()
        db_session.refresh(entry)
        assert entry.created_at is not None
