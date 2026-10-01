# Path: app/models/agent_memory.py
# File: agent_memory.py
# Created: 2026-09-29 (DWB-584)
# Purpose: AgentMemory ORM model - one row per memory in human_memory mode.
#          Persists tier, the two session references, fired_count and
#          context_key, and the cost/caught_by/surprised tags moved here
#          from journal_entries. The SCORE IS NOT STORED and must never be.
# Caller: app/models/__init__.py (re-export); the scoring read, consolidation
#         and retrieval land in DWB-585 through DWB-589, not here
# Callees: app/database.Base
# Data In: DB rows
# Data Out: AgentMemory, MemoryTier, MemoryCost, MemoryCaughtBy
# Last Modified: 2026-09-30 (DWB-611: scar_context_bound collapsed into scar -
#                Miles's ruling was four buckets, all scars context-bound, not
#                a fifth value distinguishing which ones are)

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MemoryTier(str, enum.Enum):
    """The holders from spec section 2, plus the untiered state section 4 needs.

    `raw` is NOT one of the spec's tiers. It is the state a row is written in
    before consolidation has judged it: section 4 rules that a session appends
    RAW and unsorted, because tiering in the moment rubber-stamps in-the-moment
    salience, which is the judgment consolidation exists to make.

    It is an ENUM VALUE rather than a NULL tier (DWB-584 ruling, stated in the
    ticket comment because DWB-585 and DWB-586 both build on the answer). NULL
    in this schema already means "we do not know" - hook_sessions.ticket_source
    documents that convention explicitly. An untiered row is not an unknown; it
    is a known state a writer chose. Making it a value also forces the scoring
    query to NAME it in order to exclude it, where a nullable column would let
    a join or an IS NOT NULL drop those rows silently.

    Untiered rows are excluded from scoring until consolidation tiers them.

    There is no `journal` member: the journal is its own table, and section 3
    scores it by retrieval rather than by tier.

    THERE IS NO `scar_context_bound` MEMBER (DWB-611, collapsed from DWB-584's
    original five-value enum). Miles's ruling: four buckets, no more no less,
    and ALL scars are context-bound - a fifth value distinguishing "the ones
    that are" from "the ones that aren't" should never have existed. The audit
    that found this found the split load-bearing in three places (which tier
    an agent could choose while adopting, whether context_key got populated,
    which heading memory_revert rendered under) but never load-bearing in the
    one place that would have justified two enum values: the decay curve was
    always identical for both. `context_key` is now populated for every `scar`
    row a heading path is available for, not a subset gated by which of two
    tier values was chosen. The migration
    (alembic/versions/dwb611a1b2c3_collapse_scar_context_bound.py) retiers
    every existing `scar_context_bound` row to `scar` before narrowing the
    column's ENUM, so no row silently vanishes or fails to load.
    """

    raw = "raw"
    core = "core"
    scar = "scar"
    working = "working"


class MemoryCost(str, enum.Enum):
    """What the episode this memory came from cost.

    Lives on the MEMORY, not the journal (spec section 6, second amendment
    2026-09-29). Sections 4 and 6 disagreed about where these three tags
    belonged and the tie was broken by asking what READS each field: section 2
    gates the SCAN on `cost`, and the SCAN runs over scars, which are memory
    rows. Nullable, because not every memory has a price.
    """

    none = "none"
    low = "low"
    high = "high"


class MemoryCaughtBy(str, enum.Enum):
    """Who noticed the thing this memory records.

    On the memory rather than the journal for the query section 4 justifies it
    with: everything the human had to catch is a map of where the agent's own
    checks do not look, and that is a query over lessons. Nullable: some
    memories are nobody's catch.
    """

    me = "me"
    worker = "worker"
    human = "human"
    ci = "ci"


class AgentMemory(Base):
    """One memory belonging to one agent, in human_memory mode.

    Spec: docs/human_memory_spec.md sections 2, 3 and 6 (section 6 as amended
    2026-09-29).

    THERE IS NO SCORE COLUMN AND THERE MUST NEVER BE ONE. Section 3, verbatim:
    "Score is a pure function of (tier, sessions_since_reinforced). Stored
    scores require updating every row every session and drift out of sync with
    the rule; a derived score cannot disagree with itself." A stored score is a
    second authoritative copy of a derived fact. The same reasoning rules out a
    stored band and a stored sessions_since_reinforced: the count is derived
    from last_reinforced_session_id at read time. A test in
    tests/test_human_memory_schema_dwb584.py asserts the columns' absence.

    THE CLOCK IS SESSIONS, NOT DAYS (section 3). That is why reinforcement is
    recorded as last_reinforced_session_id, a reference to a dwb_sessions row,
    rather than a timestamp. created_at and updated_at below are ordinary
    bookkeeping and are NOT the clock; nothing that decays may read them, or the
    calendar the ruling removed comes back in through the side door.
    """

    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False, index=True
    )
    tier: Mapped[MemoryTier] = mapped_column(Enum(MemoryTier), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # What a context-bound scar is bound TO. NULL for every other tier, and for
    # a context-bound scar whose context has not been named yet. The SCAN reads
    # this to ask whether the context is still alive.
    context_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # DWB-584 amendment: cost, caught_by and surprised moved here from
    # journal_entries by TL ruling on 2026-09-29, after Stan hit the collision
    # between spec sections 4 and 6. All three are READ against memories, and
    # section 7 opens by naming two stores that both look authoritative and
    # disagree as the failure mode, so they live in exactly one place.
    #
    # All three nullable. Section 4's rule is "tag only what the moment knows
    # and cannot later be reconstructed", so an untagged memory is the normal
    # case, not a defect.
    cost: Mapped[MemoryCost | None] = mapped_column(Enum(MemoryCost), nullable=True)
    caught_by: Mapped[MemoryCaughtBy | None] = mapped_column(
        Enum(MemoryCaughtBy), nullable=True
    )
    # Tri-state on purpose: True, False, and "nobody said". NULL is not False.
    # Section 1 makes prediction error the driver of encoding strength, so the
    # difference between "was not surprised" and "was never asked" is real.
    surprised: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Both nullable: a memory can be created or reinforced outside any open DWB
    # session, and a row carried in from stock memory has no originating
    # session at all. The decay count derived from last_reinforced_session_id
    # has to define its own behaviour for NULL rather than assume a row.
    created_session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dwb_sessions.id"), nullable=True
    )
    last_reinforced_session_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dwb_sessions.id"), nullable=True, index=True
    )
    # How many times this memory has FIRED - prevented an error, been cited,
    # been corrected against. Section 3: firing resets the score to 10 and
    # restarts the curve, and is the only way a score climbs. The reset is
    # recorded by moving last_reinforced_session_id; this is the tally.
    fired_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The journal entry this memory was distilled from, when it was. One
    # direction only: journal_entries does not point back, so a memory can be
    # evicted without stranding the story it came from (section 7 hard rule 4).
    source_journal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("journal_entries.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # The spawn-time load: every memory for one agent, tier-ordered.
        Index("ix_agent_memories_agent_tier", "agent_id", "tier"),
    )
