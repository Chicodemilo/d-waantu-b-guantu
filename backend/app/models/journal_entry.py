# Path: app/models/journal_entry.py
# File: journal_entry.py
# Created: 2026-09-29 (DWB-584)
# Purpose: JournalEntry ORM model - the human_memory journal. Holds the story a
#          memory came from, scores 0 until reached for, and never auto-loads.
#          Its retrieval path is tags plus date plus term.
# Caller: app/models/__init__.py (re-export), app/services/journal.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: JournalEntry
# Last Modified: 2026-09-30 (DWB-605: created_at added - the memory's ORIGINAL
#                date, distinct from entered_at's journal-arrival date)

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# NO `JournalCost` / `JournalCaughtBy` HERE, and their absence is deliberate.
#
# They briefly existed as transitional aliases to MemoryCost / MemoryCaughtBy,
# so that DWB-586's in-flight journal service kept importing while the three
# moment-tags moved onto agent_memories. That migration is finished, the
# aliases had zero consumers, and they are gone. An alias that outlives its
# migration becomes a naming ambiguity nobody can resolve from the code.
#
# The vocabulary lives in app/models/agent_memory.py, beside the columns it
# describes. Import MemoryCost / MemoryCaughtBy from there.


class JournalEntry(Base):
    """One journal entry for one agent.

    Spec: docs/human_memory_spec.md section 5, schema in section 6 as amended
    twice on 2026-09-29.

    Three properties of this table are load-bearing and easy to erode:

    1. It NEVER auto-loads. Section 3 scores the journal 0 until it is reached
       for. Nothing here belongs in a spawn payload by default.
    2. It is where things GO, not only where they are recorded. Section 7 hard
       rule 4: anything leaving memory lands in the journal first, journal then
       rewrite. That makes an eviction recoverable, which is the whole reason
       dropping a scar is safe. An agent_memories row points back at the entry
       it came from through source_journal_id; the reverse pointer deliberately
       does not exist, so a memory can be deleted without stranding its story.
    3. It does NOT carry cost, caught_by or surprised. Those describe a LESSON
       and are read against memories, so they live on agent_memories. This
       table keeps `tags` and `entered_at`, which are its own retrieval path:
       section 5 says a journal read is tags plus date plus term, never a full
       scan.
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    # Nullable for the same reason hook_sessions.dwb_session_id is: an entry can
    # be written outside any open DWB session, and historical rows must stay
    # valid. Readers counting sessions must expect to skip these.
    dwb_session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dwb_sessions.id"), nullable=True, index=True
    )
    entered_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # DWB-605: the memory's ORIGINAL date, distinct from entered_at (the date
    # it arrived in the journal). For an entry a session journals directly
    # these are the same day by construction; they diverge for DWB-607's
    # WORKING-floor eviction, which journals a memory that was created long
    # before the moment it is now leaving agent_memories. Server-defaults to
    # now() so a caller that does not pass one (every write before DWB-607
    # exists) gets the current behaviour - created_at == entered_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Free list of strings, and one half of this table's retrieval path. JSON
    # rather than a child table for now because nothing joins on a tag yet; that
    # decision was taken deliberately rather than by default, and if ranking
    # ever needs to join, it is a child table and a migration.
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # How many times this entry has been reached for. Section 3 gives a
    # retrieved entry a two-day tail (10 -> 5 -> 2 -> 0); the tail is computed
    # at read time from the retrieval, this count is the raw tally.
    retrieval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_journal_entries_agent_entered", "agent_id", "entered_at"),
    )
