# Path: app/models/memory_transition.py
# File: memory_transition.py
# Created: 2026-09-30 (DWB-593)
# Purpose: MemoryTransition ORM model - one row per candidate entry in a
#          memory-mode transition, so a mode change is the END of a per-entry
#          pipeline rather than a flag flip.
# Caller: app/models/__init__.py (re-export), app/services/project.py
#         (the cutover guard); the enumerator that fills it is DWB-594
# Callees: app/database.Base, app/models/agent_memory (tier vocabulary)
# Data In: DB rows
# Data Out: MemoryTransition, MemoryTransitionRun, TransitionDirection,
#           TransitionState, TransitionRunState
# Last Modified: 2026-09-30 (DWB-593)

"""One row per candidate entry in a memory-mode transition.

THE SHAPE IS THE POINT. Miles: "I don't want to leave it to just a giant
context list." Nobody is ever handed a whole memory file and asked to sort it
out; each entry travels its own pipeline, which also makes the work resumable
after an interruption and auditable afterwards. A single in-flight flag can be
neither.

WHAT THIS FIXES. Flipping `memory_mode` straight to `human_memory` sealed the
flat file (DWB-589) against an empty store, so every agent on the project
spawned amnesiac until someone flipped it back.

AND THE FRAMING, because the wrong reading produces a worse fix: the seal is
not defective and is not too aggressive. It does exactly what DWB-589
specified, and that was right for a flag nobody could flip without a migration
behind it. Nothing enforced that precondition, so the fix is to make the state
the seal fires in UNREACHABLE, never to give the seal exceptions. A seal with
exceptions leaks on a path nobody tested.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.agent_memory import MemoryTier


class TransitionDirection(str, enum.Enum):
    """Which way this transition runs.

    `adopt` reads the flat file and proposes rows; `revert` reads the rows and
    writes a flat file back. They are not mirror images - an adopt has a
    source_excerpt and a revert does not - which is why the direction is stored
    rather than inferred from the project's current mode. Inferring it would
    also make a row unreadable after the cutover it belongs to.
    """

    adopt = "adopt"
    revert = "revert"


class TransitionState(str, enum.Enum):
    """Where this entry has got to.

    pending -> proposed -> decided -> written is the happy path. `skipped` and
    `journaled` are the other two ways an entry can be finished with.

    TERMINAL MEANS "THE CUTOVER MAY PROCEED PAST THIS ROW", which is the only
    question the guard asks. See TERMINAL_STATES below; it is a named set
    rather than a comparison so that adding a state forces a decision about
    which side of the line it falls on, instead of defaulting to non-terminal
    and silently blocking every cutover.
    """

    pending = "pending"
    proposed = "proposed"
    decided = "decided"
    written = "written"
    skipped = "skipped"
    journaled = "journaled"


TERMINAL_STATES: frozenset[TransitionState] = frozenset(
    {TransitionState.written, TransitionState.skipped, TransitionState.journaled}
)
"""The states a cutover may proceed past.

`written` means the entry landed in the new store. `skipped` means a human or
agent decided it should not travel. `journaled` means it left as an episode
rather than a lesson, which per spec section 7 hard rule 4 is where anything
leaving memory goes first.
"""


class MemoryTransition(Base):
    __tablename__ = "memory_transitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.id"), nullable=False
    )
    # NOT NULL: an entry without a run is the orphan the run table exists to
    # make impossible. `direction` lives on the run, stated once rather than
    # repeated on every entry.
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("memory_transition_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[TransitionState] = mapped_column(
        Enum(TransitionState),
        nullable=False,
        default=TransitionState.pending,
        server_default=TransitionState.pending.value,
    )
    # The slice of the flat file this row is about. Nullable because a revert
    # has no flat-file source: its source is an agent_memories row.
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reuses MemoryTier rather than declaring a parallel vocabulary, so there is
    # one definition of what a tier is. `raw` is reachable through the shared
    # enum but is not a meaningful PROPOSAL - a proposal is a judgement and
    # `raw` is the absence of one - so the service refuses it rather than the
    # schema, keeping the vocabulary single.
    proposed_tier: Mapped[MemoryTier | None] = mapped_column(
        Enum(MemoryTier), nullable=True
    )
    decided_tier: Mapped[MemoryTier | None] = mapped_column(
        Enum(MemoryTier), nullable=True
    )
    # Free text, not an FK to agents: the decider may be an agent, a human or a
    # rule, and an FK would force the first and quietly lose the other two.
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The agent_memories row this produced. NULL until written, and NULL
    # forever for skipped and journaled rows.
    target_memory_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agent_memories.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # The cutover guard's query: non-terminal rows for one project.
        Index("ix_memory_transitions_project_state", "project_id", "state"),
        Index("ix_memory_transitions_agent_state", "agent_id", "state"),
        Index("ix_memory_transitions_target_memory_id", "target_memory_id"),
        Index("ix_memory_transitions_run_state", "run_id", "state"),
    )


class TransitionRunState(str, enum.Enum):
    """Where the RUN as a whole has got to.

    `open` is the only state the cutover guard will act on; `completed` and
    `aborted` are history. A run is never deleted, which is what makes the
    audit trail real across repeated transitions.
    """

    open = "open"
    completed = "completed"
    aborted = "aborted"


class MemoryTransitionRun(Base):
    """One transition, as an entity rather than as an implication.

    ADDED AFTER THE ENTRY TABLE ALONE PROVED INSUFFICIENT, for two reasons that
    arrived from opposite directions.

    1. THE PRECONDITION THE GUARD WAS MISSING. A cutover guard that asks only
       "is any entry unfinished" passes trivially when there are NO entries, so
       `stock -> adopting -> human_memory` sealed the flat file against an
       empty store in two calls: the original bug, walked straight through the
       machine built to prevent it. Zero entries is ambiguous between
       "enumeration ran and found nothing", a legitimate cutover for a project
       with no memory, and "enumeration never ran", which is the bug. A count
       cannot tell those apart. `enumerated_at` can.

    2. REPEATED TRANSITIONS. A project that adopts, reverts and adopts again
       has entry rows that nothing distinguishes. Without a run to hang them
       off, either the earlier rows are deleted, destroying the audit trail the
       design promised, or they are kept and every count is wrong from the
       second transition onward. A defect with no detector.

    NO COUNTS ARE STORED HERE. Entries done and total are DERIVED from
    `memory_transitions`. A stored count is a second authoritative copy that
    drifts the moment a row changes state without the header being updated,
    which is the same defect as a stored score - refused twice already in this
    lane, and refused here for the same reason.
    """

    __tablename__ = "memory_transition_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    direction: Mapped[TransitionDirection] = mapped_column(
        Enum(TransitionDirection), nullable=False
    )
    state: Mapped[TransitionRunState] = mapped_column(
        Enum(TransitionRunState),
        nullable=False,
        default=TransitionRunState.open,
        server_default=TransitionRunState.open.value,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # NULL until the DWB-594 enumerator has run for THIS run. The cutover guard
    # refuses while it is NULL, which is the fix for the two-call bug above.
    enumerated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    aborted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    # At most one OPEN run per project, enforced by the DATABASE rather than by
    # a read-check-write, which races. MySQL has no partial indexes, so this is
    # the dwb_sessions pattern: a STORED generated column that is 1 while open
    # and NULL otherwise, plus a composite UNIQUE. NULLs never collide in a
    # MySQL UNIQUE index, so closed runs do not contend.
    #
    # GENERATED: never assign to it.
    is_open: Mapped[int | None] = mapped_column(
        Integer,
        Computed("(CASE WHEN state = 'open' THEN 1 ELSE NULL END)", persisted=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("project_id", "is_open", name="uq_transition_run_one_open"),
    )
