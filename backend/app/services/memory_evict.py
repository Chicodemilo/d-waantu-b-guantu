# Path: app/services/memory_evict.py
# File: memory_evict.py
# Created: 2026-09-30 (DWB-607)
# Purpose: Execute the WORKING-floor eviction - move a WORKING memory sitting
#          at the floor into the journal, preserving its original date via
#          DWB-605's created_at column, then delete the agent_memories row.
#          The consumer scored_memory()'s `evict` list has never had.
# Caller: the session-start consolidation job (future ticket) will call
#         evict_working_memories
# Callees: app/models/agent_memory, app/services/memory_score (score(), band(),
#          sessions_since_reinforced() - the pure functions, not
#          scored_memory() itself), app/services/journal
# Data In: db Session, an optional agent_id scope
# Data Out: list[JournalEntry] created by this eviction pass
# Last Modified: 2026-09-30 (DWB-607)

"""The WORKING-floor movement, finally with a consumer.

FROM THE HUMAN MEMORY AUDIT, 2026-09-30: `memory_score.scored_memory()`
produces an `evict` list of WORKING memories at the floor, and its own
docstring already said the honest thing about it: "this list nominates; it
does not remove." Nothing consumed it. No AgentMemory row was ever deleted
anywhere in the app. This module is the consumer.

THE FLOOR IS 1, NOT 0, AND IS NOT THIS TICKET'S TO CHANGE. Miles ruled it
("working floor of 1 is fine, doesn't really change much") after this ticket
was scoped. `memory_score.MIN_DERIVED_SCORE`, `_CURVE`, `score()` and the four
tests that encode the floor are all untouched here - this module only asks
"is this memory AT the floor the curve already computes", never what the
floor's value is.

WHY THIS RECOMPUTES THE BAND DIRECTLY RATHER THAN CALLING scored_memory():
at the time this was written, `scored_memory()` was ALSO where DWB-603's
`fired_count` write site lived, and that write site was disputed pending
Miles's ruling on whether an automatic read should ever fire a scar (it
should not, and the ruling since moved firing out to
`memory_consult.consult_scars` entirely - `scored_memory()` is pure now).
This eviction consumer never had a reason to inherit that side effect just
to reach a number `score()` and `band()` already compute on their own, and
the ruling proved the instinct right, but the independence was earned before
the ruling landed, not after. Calling the pure functions directly
(`sessions_since_reinforced`, `score`, `band`) gets the same answer
`scored_memory()`'s `evict` list would, with no scar-firing
attached at all - a question that no longer needs an answer, since
`scored_memory()` cannot fire anything from anyone, ever.

JOURNAL BEFORE DELETE, IN THAT ORDER, AND IT IS TESTABLE. Same rule DWB-594's
skip path and memory_revert.py's drop path both already enforce (spec section
7 hard rule 4): the journal entry is flushed BEFORE the AgentMemory row is
deleted, so a failure between the two leaves the memory intact and the journal
merely early, never the reverse. The one unrecoverable outcome - content gone
from both places - stays unreachable the same way it does everywhere else in
this lane.

created_at CARRIES THE ORIGINAL DATE FORWARD; entered_at DOES NOT NEED TO.
`journal.create_entry(created_at=memory.created_at)` is the whole DWB-605
contract this ticket was blocked on - `entered_at` is left to its own
server_default (now()), which is correct: eviction IS when this entry
genuinely arrives in the journal, only the memory's OWN age must not be
overwritten by that moment.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import journal as journal_svc
from app.services import memory_score

# Tags every journal entry written by this eviction carries, so a human
# reading the journal later can see why the entry arrived without joining
# back to an agent_memories row that no longer exists. Same precedent as
# memory_revert.py's JOURNAL_TAGS_DROPPED and memory_decide.py's SKIP_TAGS.
EVICTION_TAGS = ["consolidation", "working-floor-eviction"]


def _working_memories_at_floor(
    db: Session, *, agent_id: int | None
) -> list[AgentMemory]:
    """Every WORKING memory currently in the last-consolidation band.

    Mirrors exactly what `scored_memory()`'s `evict` list contains - same
    exclusion of unscored rows (no session origin), same band computed from
    the same `score()`/`band()` - without going through `scored_memory()`
    itself. See the module docstring on why that split matters right now.
    """
    conditions = [AgentMemory.tier == MemoryTier.working]
    if agent_id is not None:
        conditions.append(AgentMemory.agent_id == agent_id)

    memories = list(
        db.execute(select(AgentMemory).where(*conditions).order_by(AgentMemory.id.asc()))
        .scalars()
        .all()
    )

    at_floor = []
    for memory in memories:
        gap = memory_score.sessions_since_reinforced(db, memory)
        if gap is None:
            # Same exclusion scored_memory() applies: a row with no session
            # origin is reported unscored, never a candidate for anything.
            continue
        value = memory_score.score(MemoryTier.working, gap)
        if memory_score.band(value) == memory_score.BAND_LAST_CONSOLIDATION:
            at_floor.append(memory)
    return at_floor


def evict_working_memories(
    db: Session, *, agent_id: int | None = None
) -> list[JournalEntry]:
    """Move every WORKING memory at the floor into the journal, then delete
    the agent_memories row. Returns the journal entries created.

    `agent_id=None` scopes to every agent, matching
    `memory_promote.promote_journal_candidates`'s own default - the future
    consolidation job runs this per session, not per agent.

    Idempotent by construction rather than by a check: once a memory is
    evicted its AgentMemory row is gone, so a repeated call simply finds
    nothing left to nominate. Contrast DWB-608's journal-to-core promotion,
    which RETAINS its source row and needs an explicit already-promoted
    check for exactly that reason - this movement deletes its source, so
    there is nothing left for a second pass to re-find.
    """
    candidates = _working_memories_at_floor(db, agent_id=agent_id)
    if not candidates:
        return []

    created: list[JournalEntry] = []
    for memory in candidates:
        entry = journal_svc.create_entry(
            db,
            agent_id=memory.agent_id,
            body=memory.body,
            tags=list(EVICTION_TAGS),
            created_at=memory.created_at,
        )
        # Flushed BEFORE the delete, per hard rule 4: a failure here leaves
        # the memory intact and the journal merely early, never the reverse.
        db.flush()
        db.delete(memory)
        created.append(entry)

    db.flush()
    return created
