# Path: app/services/memory_consolidate.py
# File: memory_consolidate.py
# Created: 2026-09-30 (DWB-609)
# Purpose: The session-start consolidation job - run Miles's five memory
#          movements for one agent, in the order that keeps them from
#          colliding on the same row. Fires nothing: every movement called
#          here only reads counts/signals something else already wrote and
#          acts on them.
# Caller: app/services/hook_tracking.handle_session_start, gated on
#         project.memory_mode == human_memory
# Callees: app/services/memory_promote (maybe_promote_scar,
#          promote_journal_candidates), app/services/memory_scar_conclude
#          (evict_concluded_scars), app/services/memory_evict
#          (evict_working_memories), app/services/memory_scan (SCAR_FAMILY)
# Data In: db Session, agent_id
# Data Out: ConsolidationResult - what each movement did, for the caller to
#           log and for tests to assert against
# Last Modified: 2026-09-30 (DWB-609)

"""Orchestrates the four movement consumers this lane now has, in the one
order that is not arbitrary.

FROM THE HUMAN MEMORY AUDIT, 2026-09-30: nothing fired at session start or on
any trigger. App lifespan started only idle_sweeper and marker_sweep_task,
neither touching memory. The score itself needs no job - deriving it at read
time is correct and Miles has not disputed it (see memory_score.py). What
needed a job was ACTING on the scores and the SCAN, which is this module.

THIS JOB MOVES THINGS AND COUNTS NOTHING, BY CONSTRUCTION, NOT BY CONVENTION.
Miles's ruling on the fire/pull question, relayed verbatim: "Deploy doesn't
count as a read. Reading is Oh have I made this scar producing error before?
Outside of normal startup." Session-start consolidation runs AT the moment
that quote names as NOT a read. The three functions this module calls -
`maybe_promote_scar`, `evict_concluded_scars`, `evict_working_memories`,
`promote_journal_candidates` - each already avoid `scored_memory()` and the
journal's firing/retrieval machinery entirely, reading `fired_count` and
`retrieval_count` as plain columns and acting on what they find. There is
nothing in this module that could fire anything even by mistake, because none
of its callees have a write site for either counter - Stan's `memory_score.py`
strip-down and the (still separate, consultation-only) scar-consult surface
own that question entirely, and this module does not need to know how it
resolved to be correct.

THE ORDER, AND WHY IT IS NOT ARBITRARY. Two of the four movements can touch
the SAME agent_memories row - a scar can independently satisfy
`fired_count >= 3` (promote to CORE) and have a context_key that happens to
read as concluded (evict to journal) in the same pass. `memory_scan.
scan_context` only ever returns one `ContextLiveness` per call, so these are
never BOTH true from one scan - the collision is between `fired_count` and
whatever `scan_context` says, not within `scan_context` itself. If eviction
ran first, a scar that had fired three times could be deleted before its
recurrence was ever rewarded, which contradicts Miles's own reasoning for the
fired-three-times rule (recurrence while held is evidence the lesson is
durable - that outranks "the specific episode is now historical"). So:

1. SCAR -> CORE first (`maybe_promote_scar`, per scar-family candidate). A
   row promoted here changes `tier` to `core` and leaves `memory_scan.
   SCAR_FAMILY` immediately, so step 2's query - taken fresh, after this loop
   - never sees it.
2. SCAR CONTEXT CONCLUDED -> journal (`evict_concluded_scars`), on whatever
   scar-family rows remain after step 1.
3. WORKING FLOOR -> journal (`evict_working_memories`). Independent tier,
   disjoint from steps 1-2 by construction (WORKING is never scar-family), so
   it carries no ordering dependency on them and runs here only because that
   is as good a place as any.
4. JOURNAL -> CORE (`promote_journal_candidates`). A different table
   (journal_entries, not agent_memories) with its own idempotence
   (`source_journal_id` already-promoted check), so nothing above can affect
   its candidates - a memory evicted in steps 2-3 creates a BRAND NEW journal
   entry at retrieval_count 0, nowhere near DWB-608's threshold, in the same
   pass that would promote it.

NO AGENT_ID SCOPE ON THE INDIVIDUAL CALLS BELOW BEYOND WHAT THIS FUNCTION
PASSES. `evict_working_memories` and `promote_journal_candidates` both default
to `agent_id=None` (every agent) for other callers; this module always passes
the one agent whose session just started, because a session-start job for
agent A has no business moving agent B's memories. Scoping is this module's
job, not something to rely on a shared default for.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.models.journal_entry import JournalEntry
from app.services import memory_evict, memory_promote, memory_scan, memory_scar_conclude


@dataclass
class ConsolidationResult:
    """What one consolidation pass did for one agent. Four lists, not a
    single tally - a caller or a test needs to tell WHICH movement produced
    which effect, not just that four things is the right total."""

    promoted_scars: list[tuple[int, str]] = field(default_factory=list)
    """(memory_id, ScarPromotionReason.value) for every scar promoted to CORE
    in this pass - both the fired-three-times and context-cannot-die
    triggers land here, distinguished by the reason string."""

    concluded_scars: list[JournalEntry] = field(default_factory=list)
    """Journal entries created by evicting a scar whose context concluded."""

    evicted_working: list[JournalEntry] = field(default_factory=list)
    """Journal entries created by evicting a WORKING memory at the floor."""

    promoted_journal: list[AgentMemory] = field(default_factory=list)
    """New CORE memories created from journal entries at or past the
    promotion threshold."""

    @property
    def moved_anything(self) -> bool:
        """True if this pass had any effect at all. A quiet pass (nothing met
        any trigger) is the overwhelmingly common case and is not an error -
        this is for a caller that wants to skip logging a no-op pass."""
        return bool(
            self.promoted_scars
            or self.concluded_scars
            or self.evicted_working
            or self.promoted_journal
        )


def _scar_family_candidates(db: Session, *, agent_id: int) -> list[AgentMemory]:
    """Every scar-family AgentMemory row for this agent, read fresh.

    Not `scored_memory()`: that function's own firing question is Stan's to
    resolve and this module does not depend on the answer either way, same
    reasoning memory_evict.py and memory_scar_conclude.py already apply. This
    is a plain, unfiltered-by-score query because `maybe_promote_scar` makes
    its own fired_count/context decision per row; there is no "at rest" or
    "at the floor" precondition for scar-to-core the way there is for the
    other two movements.
    """
    return list(
        db.execute(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent_id)
            .where(AgentMemory.tier.in_(memory_scan.SCAR_FAMILY))
            .order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )


def consolidate_agent(db: Session, *, agent_id: int) -> ConsolidationResult:
    """Run all four movements for one agent, in the order the module
    docstring justifies. Does not commit - the caller (the session-start hook
    handler) owns the transaction, same split every service in this lane
    uses.
    """
    result = ConsolidationResult()

    # 1. Scar -> CORE first.
    for memory in _scar_family_candidates(db, agent_id=agent_id):
        reason = memory_promote.maybe_promote_scar(db, memory)
        if reason is not None:
            result.promoted_scars.append((memory.id, reason.value))

    # 2. Scar context concluded -> journal, on whatever remains after step 1.
    result.concluded_scars = memory_scar_conclude.evict_concluded_scars(
        db, agent_id=agent_id
    )

    # 3. WORKING floor -> journal. Independent tier.
    result.evicted_working = memory_evict.evict_working_memories(
        db, agent_id=agent_id
    )

    # 4. Journal -> CORE. Independent table.
    result.promoted_journal = memory_promote.promote_journal_candidates(
        db, agent_id=agent_id
    )

    return result
