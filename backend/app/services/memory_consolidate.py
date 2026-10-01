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

from app.models.agent_memory import AgentMemory, MemoryCaughtBy, MemoryCost, MemoryTier
from app.models.journal_entry import JournalEntry
from app.models.agent import Agent
from app.services import dwb_session, memory_evict, memory_promote, memory_scan, memory_scar_conclude


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

    tiered_raw: list[tuple[int, str]] = field(default_factory=list)
    """(memory_id, MemoryTier.value) for every RAW row this pass judged.

    DWB-632. Separate from the other four because it is the only movement that
    creates eligibility rather than acting on it: a row leaving `raw` becomes
    scoreable, renderable and injectable for the first time.
    """

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
            or self.tiered_raw
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


def _active_session_id(db: Session, agent_id: int) -> int | None:
    """The DWB session this consolidation is happening inside, or None.

    Same resolution journal.py and memory_consult.py use: agent -> project ->
    active session. None is a legitimate answer; see `tier_raw_memories` for
    what it causes.
    """
    agent = db.get(Agent, agent_id)
    if agent is None or agent.project_id is None:
        return None
    active = dwb_session.get_active_session(db, agent.project_id)
    return active.id if active is not None else None


def tier_for_raw(memory: AgentMemory) -> MemoryTier:
    """Which tier a RAW row earns, from the tags the MOMENT captured.

    DWB-632. Spec section 4 says append raw and unsorted during a session,
    because "tiering in the moment rubber-stamps in-the-moment salience, which
    is the judgment CONSOLIDATION exists to make". It assigns that judgment to
    consolidation in plain words; nothing was ever built to carry it out, so
    `raw` was terminal in practice and 39 rows of one evening's lessons sat
    permanently unscoreable while a docstring promised they would be tiered.

    THE INPUTS ARE THE ONLY ONES SECTION 4 SAYS SURVIVE THE MOMENT. It tells an
    agent to "tag only what the moment knows and cannot later be
    reconstructed": `cost`, `caught_by`, `surprised`. This reads exactly those
    and nothing else. Reading the BODY instead would be judging salience from
    text at a moment the spec says is the wrong moment, by a mechanism with no
    reader in the loop.

    WHAT EARNS A SCAR. Any ONE of:
      - `cost: high`            it actually cost something
      - `surprised: True`       it contradicted expectation, which is what a
                                lesson IS
      - `caught_by:` not `me`   somebody else found it, and section 4 says
                                "everything the human had to catch is a map of
                                where the agent's own checks do not look"

    EVERYTHING ELSE BECOMES `working`, INCLUDING EVERY ROW WITH NO TAGS AT ALL,
    and that default is the safety mechanism rather than a preference:

      - Down from UNKNOWN is `working`. The adoption rule "tier down on
        uncertainty" pointed at `scar` only because the alternative there was
        `core`; the ordering is core > scar > working.
      - `working` is outside `memory_scan.SCAR_FAMILY`, so `consult_scars`
        never fires it, so `fired_count` never reaches SCAR_FIRED_THRESHOLD,
        so `maybe_promote_scar` can never send an UNJUDGED row to CORE - the
        tier that never decays. Defaulting to `scar` instead would make an
        untagged scratch note promotable to a permanent memory with no
        judgment by anyone, which is the rubber-stamp section 4 forbids
        arriving late and automatically. The default does that work
        STRUCTURALLY; there is no guard here to maintain or forget.
      - A `working` row decays and is journaled at its floor under hard rule 4,
        so an unjudged note nobody ever reaches for fades into the journal
        rather than resting at 6 forever pretending to be an earned lesson.

    WHAT THIS IS NOT. It is not the SCAN (section 2), which re-examines resting
    scars against the current context and is the genuinely model-shaped
    judgment. It is not a way for an agent to re-judge a tier it disagrees
    with. Neither exists yet. A working mechanism here must not be read as
    section 4 being finished.
    """
    if memory.cost == MemoryCost.high:
        return MemoryTier.scar
    if memory.surprised is True:
        return MemoryTier.scar
    if memory.caught_by is not None and memory.caught_by != MemoryCaughtBy.me:
        return MemoryTier.scar
    return MemoryTier.working


def _raw_candidates(db: Session, *, agent_id: int) -> list[AgentMemory]:
    """Every RAW row for this agent, oldest first."""
    return list(
        db.execute(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent_id)
            .where(AgentMemory.tier == MemoryTier.raw)
            .order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )


def tier_raw_memories(db: Session, *, agent_id: int) -> list[tuple[int, str]]:
    """Move this agent's RAW rows out of `raw`. Does not commit.

    THE INVARIANT THIS MAINTAINS: a row only leaves `raw` when it will be
    SCOREABLE once it gets there. Tiering a row that cannot be scored swaps one
    permanently invisible state for another and would satisfy DWB-632's
    criterion while leaving the lesson exactly as stranded.

    That matters because of the hole this ticket was originally filed about.
    `project.delete_project` NULLS both session origins on rows it is tearing
    down, and it deliberately does not journal `raw` rows, because journaling
    pre-judgment content contradicts what `raw` means. Correct on both counts.
    The consequence was that such a row could never BECOME scoreable - and
    before this function existed there was no moment at which to fix it.

    Now there is. Tiering IS that moment, so a row arriving here with no origin
    at all gets one: the session in which it is being judged. That value is
    TRUE in the way the DWB-621 contract requires - the row is becoming a
    memory now, and the decay clock should run from now - rather than a
    reconstructed date nobody can stand behind. `created_session_id` and not
    `last_reinforced_session_id`, because "reinforced" means recalled and this
    row has never been recalled.

    AND IF THERE IS NO SESSION TO STAMP, THE ROW STAYS RAW. It is left for a
    later pass rather than tiered into invisibility. A row can sit raw for
    another session; a tiered row with no origin is stuck forever, because
    nothing would ever look at it again.
    """
    active_id = _active_session_id(db, agent_id)
    moved: list[tuple[int, str]] = []
    for memory in _raw_candidates(db, agent_id=agent_id):
        has_origin = (
            memory.created_session_id is not None
            or memory.last_reinforced_session_id is not None
        )
        if not has_origin:
            if active_id is None:
                # Nothing truthful to stamp. Leave it raw for a later pass.
                continue
            memory.created_session_id = active_id
        tier = tier_for_raw(memory)
        memory.tier = tier
        moved.append((memory.id, tier.value))
    if moved:
        db.flush()
    return moved


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

    # 5. RAW -> scar/working, and it runs LAST on purpose (DWB-632).
    #
    # Tiering first would let a row be judged and EVICTED in the same pass: a
    # raw note that has sat through many sessions becomes `working` already at
    # its floor, and step 3 would journal and delete it immediately. It would
    # be journaled first, so nothing is lost under hard rule 4, but the lesson
    # would go from written to gone without ever once being visible to anyone.
    # Running last gives every newly judged row a full session of visibility
    # before any movement can act on it; the next pass judges it on equal terms
    # with everything else.
    result.tiered_raw = tier_raw_memories(db, agent_id=agent_id)

    return result
