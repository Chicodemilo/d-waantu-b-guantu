# Path: app/services/memory_scar_conclude.py
# File: memory_scar_conclude.py
# Created: 2026-09-30 (DWB-609)
# Purpose: Execute the fifth movement - a scar at rest (score 6) whose context
#          has CONCLUDED moves into the journal, preserving its original date
#          via DWB-605's created_at column, then the agent_memories row is
#          deleted. The consumer app/services/memory_scan.ContextLiveness
#          .finished has never had.
# Caller: app/services/memory_consolidate.consolidate_agent (DWB-609)
# Callees: app/models/agent_memory, app/services/memory_score (score(),
#          sessions_since_reinforced() - the pure functions, not
#          scored_memory() itself), app/services/memory_scan (scan_context,
#          SCAR_FAMILY), app/services/journal
# Data In: db Session, an optional agent_id scope
# Data Out: list[JournalEntry] created by this eviction pass
# Last Modified: 2026-09-30 (DWB-609)

"""The fifth movement, finally with a consumer.

FROM THE HUMAN MEMORY AUDIT, 2026-09-30 AND ITS DWB-609 ADDENDUM: of Miles's
five movements, four had a hand (DWB-606 both scar-to-core paths, DWB-607 the
WORKING floor, DWB-608 journal-to-core). The fifth - "a scar at 6 whose
context is finished moves into the journal" - got a SCAN
(`memory_scan.scan_context` can answer `ContextLiveness.finished`) and no
actor. Grepping the app for that outcome outside memory_scan.py itself found
zero consumers. This module is the consumer, filed under DWB-609 because that
is where the gap was found and the ticket history should show it rather than
a silent scope expansion of DWB-606/607.

A SIBLING FILE, NOT A SIBLING FUNCTION IN memory_evict.py, DELIBERATELY.
memory_evict.py is DWB-607's delivered file, scoped tightly to the
WORKING-floor movement in its own header. This movement shares its SHAPE
(journal-before-delete, same tags-and-provenance pattern, same
created_at-carries-forward contract) but not its TRIGGER (a SCAN result, not a
score/band computation) or its TIER (scar-family, not WORKING). Keeping it in
its own file means DWB-607's file still says exactly what DWB-607 built, and
this one says exactly what DWB-609 added - the same reasoning that kept this
whole lane's modules one-movement-per-file rather than one-grab-bag-file.

"AT REST (SCORE 6)", NOT EVERY SCAR-FAMILY ROW, MATCHING THE SPEC'S OWN WORDS.
Spec section 2: "Entries sitting at 6 get periodically re-examined against the
current context." A context's liveness does not depend on how recently the
scar fired - a context can conclude on day one as easily as after ninety
sessions - but the spec scopes WHEN the re-examination runs to resting
entries, not every entry on every pass. Scoping candidates to `score() == 6`
(the resting value for FIRING_TIERS, memory_score._CURVE) matches that
wording exactly rather than scanning everything on every consolidation pass.
A scar still climbing toward 6 is presumably still being actively reinforced
and is not what section 2 means by "sitting at 6".

A MISSING OR BLANK context_key IS HANDLED BY scan_context ITSELF, NOT HERE.
Per the DWB-604/611 sequencing ruling (Archie + Stan + Barry, 2026-09-30), a
scar with no context_key now means `still_active` (take no action), not
`cannot_die` and not `finished`. This module does not pre-filter on
context_key presence; it hands every resting scar-family row to
`scan_context` and acts only on `finished`, which already encodes that rule.

ORDERING WITH SCAR-TO-CORE PROMOTION IS THE CALLER'S JOB, NOT THIS MODULE'S.
A scar can independently qualify for `cannot_die` (promote to CORE,
DWB-606/memory_promote.maybe_promote_scar) and, in principle, reach a
`finished` context_key read a session later - but never both in the SAME
read, because `scan_context` returns exactly one `ContextLiveness` value per
call and `cannot_die` and `finished` are mutually exclusive outcomes of the
same branch (a context_key either resolves to a closed ticket/epic, in which
case it is `finished` if closed else `still_active`, or it resolves to
nothing at all, which is `cannot_die` - never both for one key). The real
ordering hazard is between THIS movement and `fired_count`-triggered
promotion: a scar can satisfy both `fired_count >= 3` (promote) and have a
context that happens to have JUST concluded (evict) on the same pass, and
promoting first removes it from scar-family before this module's query ever
sees it - which is the correct outcome per Miles's own reasoning (recurrence
while held is evidence the lesson is durable, which outranks "the specific
episode that produced it is now historical"). `memory_consolidate.py` is
responsible for running promotion before this module in one consolidation
pass; this module does not re-check tier after the fact, it trusts its own
query, taken at call time, to already reflect the caller's ordering.

created_at CARRIES THE ORIGINAL DATE FORWARD; entered_at DOES NOT NEED TO.
Identical reasoning to DWB-607's evict_working_memories: `journal.create_entry
(created_at=memory.created_at)` is DWB-605's contract, `entered_at` is left to
its own server_default (now()) because concluding IS when this entry
genuinely arrives in the journal, only the memory's own age must survive.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.services import journal as journal_svc
from app.services import memory_scan
from app.services import memory_score

# Tags every journal entry written by this movement carries, so a human
# reading the journal later can see why the entry arrived without joining
# back to an agent_memories row that no longer exists. Same precedent as
# memory_evict.EVICTION_TAGS, memory_revert.JOURNAL_TAGS_DROPPED and
# memory_decide.SKIP_TAGS.
CONCLUDED_TAGS = ["consolidation", "context-concluded"]

# The resting value for any FIRING_TIERS curve (memory_score._CURVE), spec
# section 3's "31-90" bucket and beyond. Not imported from memory_score
# because nothing there names it as a constant - it is read directly off the
# curve here, once, with the citation rather than a magic number repeated.
_RESTING_SCORE = 6


def _scars_at_rest(db: Session, *, agent_id: int | None) -> list[AgentMemory]:
    """Every scar-family row whose derived score is at the resting value.

    Mirrors memory_evict._working_memories_at_floor's shape exactly, for the
    sibling movement: same unscored-row exclusion (no session origin), same
    direct calls to the pure score functions rather than `scored_memory()` -
    see the module docstring on why going through that function is not an
    option here regardless of how its own firing question resolves.
    """
    conditions = [AgentMemory.tier.in_(memory_scan.SCAR_FAMILY)]
    if agent_id is not None:
        conditions.append(AgentMemory.agent_id == agent_id)

    memories = list(
        db.execute(select(AgentMemory).where(*conditions).order_by(AgentMemory.id.asc()))
        .scalars()
        .all()
    )

    at_rest = []
    for memory in memories:
        gap = memory_score.sessions_since_reinforced(db, memory)
        if gap is None:
            # Same exclusion scored_memory() applies: a row with no session
            # origin is reported unscored, never a candidate for anything.
            continue
        if memory_score.score(MemoryTier.scar, gap) == _RESTING_SCORE:
            at_rest.append(memory)
    return at_rest


def evict_concluded_scars(
    db: Session, *, agent_id: int | None = None
) -> list[JournalEntry]:
    """Move every resting scar whose context has concluded into the journal,
    then delete the agent_memories row. Returns the journal entries created.

    `agent_id=None` scopes to every agent, matching
    `memory_evict.evict_working_memories` and
    `memory_promote.promote_journal_candidates`'s own defaults - the
    consolidation job runs this per session, not per agent.

    Idempotent by construction, same reasoning as evict_working_memories:
    once a scar is evicted its agent_memories row is gone, so a repeated call
    simply finds nothing left to nominate.
    """
    candidates = _scars_at_rest(db, agent_id=agent_id)
    if not candidates:
        return []

    created: list[JournalEntry] = []
    for memory in candidates:
        if memory_scan.scan_context(db, memory) != memory_scan.ContextLiveness.finished:
            continue
        entry = journal_svc.create_entry(
            db,
            agent_id=memory.agent_id,
            body=memory.body,
            tags=list(CONCLUDED_TAGS),
            created_at=memory.created_at,
        )
        # Flushed BEFORE the delete, per hard rule 4: a failure here leaves
        # the memory intact and the journal merely early, never the reverse.
        db.flush()
        db.delete(memory)
        created.append(entry)

    db.flush()
    return created
