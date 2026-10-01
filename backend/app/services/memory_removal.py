# Path: app/services/memory_removal.py
# File: memory_removal.py
# Created: 2026-10-01 (DWB-626)
# Purpose: THE single implementation of taking a row out of agent_memories -
#          journal it, break the inbound FK, then delete. Every removal path in
#          the system calls this; none of them reimplements the order.
# Caller: app/services/memory_withdraw.py (DWB-626); intended for
#         app/services/memory_evict.py and app/services/memory_scar_conclude.py
# Callees: app/services/journal (hard rule 4), app/models/agent_memory,
#          app/models/memory_transition
# Data In: db Session, an AgentMemory, journal tags, an optional reason
# Data Out: the JournalEntry written before the row went
# Last Modified: 2026-10-01 (DWB-626)

"""Removing a memory has two halves and until now no path had both.

    memory_evict / memory_scar_conclude   journal, flush, delete   -- no FK break
    project.abort_transition              break the FK, delete     -- no journal

Each is correct about its own half and incomplete on the other, which is why
this is a module rather than a line copied into a third place.

WHY THE FK HALF IS NOT OPTIONAL, MEASURED RATHER THAN ASSUMED.
`memory_transitions.target_memory_id` references `agent_memories` with delete
rule NO ACTION, and every adopted row is referenced, because adoption is what
created it. So a bare `db.delete(memory)` on an adopted row raises 1451.
Verified inside a rolled-back transaction with a positive control: an adopted
row REFUSED, a raw-path row SUCCEEDED, so the refusal is the constraint and not
a broken probe. The deletable set is EXACTLY the raw set, checked in both
directions rather than by subtraction (0 non-raw unpointed, 0 raw pointed).

That defect is LATENT, not live: neither eviction path has ever had a candidate,
and the journal holds 6 entries, all adoption skips, so no eviction has ever
journaled anything. But when it fires it fires at full size. Every row shares one
clock origin and that session is still open, so WORKING decays in lockstep and
the candidates reach the floor together; the first sweep afterwards hits the FK
on every one of them at once, inside the try/except at hook_tracking.py:348 that
rolls back and logs, where 1451 reads identically to "nothing to evict" and the
journal entry rolls back with it leaving no trace anywhere.

WHY DELETE AND NOT A TOMBSTONE (Archie's ruling, DWB-626). A soft-delete flag is
an absence-shaped guard across an UNBOUNDED consumer set: every present and
future reader of agent_memories would need `WHERE withdrawn_at IS NULL`, and one
that forgets serves withdrawn content - failing in the flattering direction,
silently. No test can cover it, because the consumer that forgets does not exist
yet. Deletion has no such failure mode: a row that is gone is gone for every
reader, including the ones nobody has written.

WHAT IS PRESERVED, so this is a retraction rather than an erasure. The body goes
to the journal, which is append-only, never auto-loaded and free until reached
for, carrying the memory's ORIGINAL created_at rather than today's date. The
transition row keeps its `decided_tier` and `decided_by`, so the record that a
decision was made survives; only the pointer to a row that no longer exists is
cleared. That is what lets a withdrawal supersede a lesson without losing the
fact that it was once believed, which is the case this was built for.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.models.journal_entry import JournalEntry
from app.models.memory_transition import MemoryTransition
from app.services import journal as journal_svc


def journal_and_remove(
    db: Session,
    memory: AgentMemory,
    *,
    tags: list[str],
    reason: str | None = None,
) -> JournalEntry:
    """Journal the memory, clear what points at it, then delete it.

    THE ORDER IS THE CONTRACT AND IT IS TESTABLE:

      1. write the journal entry
      2. FLUSH, so a failure after this leaves the memory intact and the journal
         merely early - never the reverse (spec section 7 hard rule 4: anything
         leaving memory lands in the journal FIRST; losing it in flight is the
         one unrecoverable mistake in the design)
      3. NULL every `memory_transitions.target_memory_id` pointing at this row
      4. delete the row

    Does NOT commit. The caller owns the transaction, so the journal entry, the
    FK break and the delete land together or not at all. That is what makes step
    2's guarantee hold under a crash rather than only under a clean return.
    """
    body = memory.body
    if reason:
        # Appended rather than put in `tags`: tags are a controlled vocabulary
        # the journal search filters on, and a free-text reason in there would
        # make every retraction its own unsearchable tag.
        body = f"{body}\n\nWithdrawn: {reason}"

    entry = journal_svc.create_entry(
        db,
        agent_id=memory.agent_id,
        body=body,
        tags=list(tags),
        # DWB-605: the memory's own date. This entry is being written now, but
        # the lesson existed from `created_at`, and dating it today would make
        # the journal claim it was learned at the moment it was retracted.
        created_at=memory.created_at,
    )
    # Step 2. `create_entry` already flushes, so this is belt and braces rather
    # than load-bearing - and it stays because the guarantee above is about THIS
    # function's order, not about what a callee currently happens to do.
    db.flush()

    # Step 3. Scoped to THIS memory id, deliberately narrower than
    # project.abort_transition, which NULLs target_memory_id for an entire
    # project because it is tearing down every staged row at once. Doing that
    # here would clear the pointers of rows that are not being removed, losing
    # provenance for memories that still exist.
    db.execute(
        update(MemoryTransition)
        .where(MemoryTransition.target_memory_id == memory.id)
        .values(target_memory_id=None)
    )

    # Step 4.
    db.delete(memory)
    db.flush()
    return entry
