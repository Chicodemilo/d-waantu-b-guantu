# Path: app/services/memory_promote.py
# File: memory_promote.py
# Created: 2026-09-30 (DWB-606)
# Purpose: Write tier=core. The single shared write path DWB-606 (scar to
#          core) and DWB-608 (journal to core) both go through, plus the two
#          movements that use it: the scar-to-core check (fired_count / the
#          context-liveness scan) and the journal-to-core consumer of
#          journal.promotion_candidates().
# Caller: the session-start consolidation job (future ticket) will call
#         maybe_promote_scar and promote_journal_candidates; both call
#         promote_to_core, which nothing else may
# Callees: app/models/agent_memory, app/services/memory_scan,
#          app/services/journal (DWB-608: promotion_candidates),
#          app/services/memory_origin (DWB-637: the insert needs an origin)
# Data In: db Session, an AgentMemory (scar family), or an agent_id scope for
#          the journal consumer
# Data Out: the promoted/created AgentMemory; ScarPromotionReason | None;
#           list[AgentMemory] newly created from journal entries
# Last Modified: 2026-10-07 (DWB-637: the journal-to-core INSERT stamps a
#                session origin and is deferred when there is none, instead of
#                minting a CORE row that can never be scored or rendered;
#                previous entry: DWB-608 journal-to-core consumer, idempotent
#                on source_journal_id)

"""Scar to CORE, and the one door CORE is written through.

FROM THE HUMAN MEMORY AUDIT, 2026-09-30: nothing in the entire app ever wrote
`tier = core`. The adopt flow (memory_decide.py) explicitly REFUSES core as a
choice - `DECIDABLE_TIERS` excludes it, by design, because section 7 hard rule
5 rules CORE a human judgement, never touched by an agent adopting its own
back catalogue. That refusal stands; this module does not reopen it. What it
opens is Miles's own two AUTOMATIC triggers for a SCAR specifically, which are
a different rule from the one memory_decide.py enforces:

1. A scar's fired_count reaches 3 (DWB-603 is the counter; SCAR_FIRED_THRESHOLD
   here is the rule that reads it).
2. The context-liveness scan (DWB-604) classifies a scar's context as one that
   structurally can never conclude (`ContextLiveness.cannot_die`).

Both are evidence a human already put in motion - firing enough times, or
having named a context nothing tracks - so this is the recurrence-driven path
section 7 hard rule 5 itself carves out as the exception to "only a human
promotes to CORE", not a second door into the same room. `memory_decide.py`'s
refusal is about a DIFFERENT rule (an ADOPTING agent guessing its own tier) and
is untouched by this module.

ON `SCAR_FIRED_THRESHOLD` SHARING THE VALUE 3 WITH `journal.PROMOTION_THRESHOLD`:
they are not the same rule and must not be collapsed into one constant. One
counts retrievals of a JOURNAL entry (spec section 5); this one counts firings
of a SCAR (spec section 2). They currently happen to agree on 3, and that is a
coincidence of two independent tunings, not a shared invariant - the exact
"two numbers where the spec ruled once" trap journal.py's own docstring warns
about would be importing one into the other and pretending a change to either
rule updates both. Two named constants, two doc citations, one accidental
number in common.

`promote_to_core` IS THE SINGLE WRITE SITE for `tier = MemoryTier.core`
anywhere in the app, used by both directions core is ever reached:

- Retiering an EXISTING AgentMemory row in place (this ticket's scar path -
  `memory=` given, id and fired_count history survive, only tier and
  context_key change; context_key is cleared because CORE is context-free by
  definition).
- Creating a NEW row from content that has no AgentMemory row of its own yet
  (DWB-608's journal path - a JournalEntry is a different table, so promoting
  one to CORE has nothing to retier and must construct a row).

One function rather than two write paths is the ticket's own requirement:
"the two should not duplicate the write path." A second implementation of
"set tier=core" is exactly how the app ends up with two places that can
disagree about what CORE means.

DWB-608: THE JOURNAL ENTRY IS RETAINED, NEVER DELETED, ON PROMOTION. Two
existing precedents decide this rather than a fresh judgement call: journal.py
provides no delete route on journal_entries at all, by design (append-only,
section 7 hard rule 4's whole reason for existing); and memory_revert.py's own
docstring rules "the journal survives frozen and untouched" for the one other
place content already leaves it. Promotion follows the same rule. The new
CORE row's `source_journal_id` is the provenance link; the journal keeps the
story it came from.

THAT RETENTION MAKES IDEMPOTENCE THE HARD PART, NOT THE WRITE. An entry stays
at or above `journal.PROMOTION_THRESHOLD` retrievals forever once it gets
there - the journal's own per-entry retrieval tally never decays, by design -
so `journal.promotion_candidates()` will keep naming the SAME entry on every
future call. A future session-start consolidation job is expected to invoke
`promote_journal_candidates` once per session; without a check, that mints a
new CORE memory from the same story every single session. `source_journal_id`
already exists as a real column for exactly this kind of provenance, so
`promote_journal_candidates` queries it before acting: an entry already linked
to an AgentMemory row is skipped, not re-promoted.
"""

import enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import journal as journal_svc
from app.services import memory_origin
from app.services import memory_scan

# Spec section 2: "a scar fired three times broadens to CORE." Deliberately
# its own constant - see the module docstring on why this must never import
# or be imported by journal.PROMOTION_THRESHOLD despite sharing a value today.
SCAR_FIRED_THRESHOLD = 3


class ScarPromotionReason(str, enum.Enum):
    """Which of Miles's two triggers fired. Named rather than a bare bool so
    a caller (and a test) can tell WHICH rule promoted a given scar, not just
    that promotion happened - the two triggers are independent evidence and
    collapsing them into one signal would make a future bug in either one
    invisible from the outside."""

    fired_three_times = "fired_three_times"
    context_cannot_die = "context_cannot_die"


def promote_to_core(
    db: Session,
    *,
    agent_id: int,
    body: str,
    memory: AgentMemory | None = None,
    source_journal_id: int | None = None,
) -> AgentMemory:
    """THE ONLY WRITE SITE for `tier = MemoryTier.core` in the application.

    `memory` given: retier that EXISTING row in place. Its id, fired_count,
    created_at and session references all survive untouched - only `tier`
    changes and `context_key` is cleared, because a context-bound scar's
    whole reason for carrying one stops applying the moment it is no longer
    context-bound at all.

    `memory` omitted: construct a NEW row from `agent_id` and `body`, with
    `source_journal_id` set when the content came from a journal entry
    (DWB-608). There is no existing AgentMemory row for a journal entry to
    retier, so this branch is a plain insert, not a promotion of something
    already in this table.

    DWB-637: THE INSERT BRANCH NEEDS A SESSION ORIGIN AND THE RETIER BRANCH
    DOES NOT, and that asymmetry is the whole of the change here. A retier
    moves an existing row's tier and leaves its session references untouched -
    the origin it already had is still true. An insert mints a row, and a minted
    row with no origin cannot be scored, so it is excluded from every candidate
    list and never reaches an agent. CORE makes that worse rather than better:
    the curve scores it 10 in every bucket, so a CORE row is the one tier that
    should never be missing from a context, and it was being written here with
    no origin at all. This writer was not named in the ticket; it is the third
    with the same defect, and a NOT NULL constraint on `created_session_id`
    would have turned it into an IntegrityError inside a hook.

    Raises `memory_origin.MemoryOriginMissing` on the insert branch when no
    DWB session is open. The background caller below never reaches that raise
    because it checks first and defers; the raise is here so that a future
    caller of this function - the single write site for CORE - cannot mint an
    unreachable row by not knowing to check.
    """
    if memory is not None:
        memory.tier = MemoryTier.core
        memory.context_key = None
        db.flush()
        return memory

    agent = db.get(Agent, agent_id)
    if agent is None or agent.project_id is None:
        raise memory_origin.MemoryOriginMissing(
            f"Journal promotion refused: agent {agent_id} is missing or has no "
            "project, so there is no project whose open DWB session could give "
            "this memory a clock origin. A memory with no origin cannot be "
            "scored and never reaches an agent."
        )
    origin = memory_origin.require_session_origin(
        db, project_id=agent.project_id, action="Journal promotion"
    )

    row = AgentMemory(
        agent_id=agent_id,
        tier=MemoryTier.core,
        body=body,
        # Never conditional. `origin` is a session or this line was not reached.
        created_session_id=origin.id,
        source_journal_id=source_journal_id,
    )
    db.add(row)
    db.flush()
    return row


def maybe_promote_scar(db: Session, memory: AgentMemory) -> ScarPromotionReason | None:
    """Check Miles's two scar-to-core triggers against one scar, promoting it
    if either fires. Returns which one fired, or None if neither did.

    fired_count is checked FIRST because it is a plain in-memory comparison,
    where the context-liveness scan does real lookups against tickets and
    epics; short-circuiting on the cheap check first avoids that work on the
    (expected to be common) majority of scars that have already fired enough
    times without ever needing their context resolved. The two triggers are
    "either", not "first", per Miles's rule - this ordering is an efficiency
    choice, not a priority ranking, and a scar that satisfies both still
    reports whichever one this function happened to check first.

    Raises the same `memory_scan.ScanError` the scan itself raises for a
    non-scar-family tier, rather than defining a second error type for the
    identical condition.
    """
    if memory.tier not in memory_scan.SCAR_FAMILY:
        raise memory_scan.ScanError(
            "not_a_scar",
            f"scar-to-core promotion is only defined for scar-family memories "
            f"({', '.join(t.value for t in memory_scan.SCAR_FAMILY)}); memory "
            f"{memory.id} is tier {memory.tier.value}",
        )

    if memory.fired_count >= SCAR_FIRED_THRESHOLD:
        promote_to_core(db, agent_id=memory.agent_id, body=memory.body, memory=memory)
        return ScarPromotionReason.fired_three_times

    if memory_scan.scan_context(db, memory) == memory_scan.ContextLiveness.cannot_die:
        promote_to_core(db, agent_id=memory.agent_id, body=memory.body, memory=memory)
        return ScarPromotionReason.context_cannot_die

    return None


def promote_journal_candidates(
    db: Session, *, agent_id: int | None = None
) -> list[AgentMemory]:
    """DWB-608: promote every eligible journal entry to a new CORE memory.

    "Eligible" is `journal.promotion_candidates()` (the entry's own tally at or past
    `journal.PROMOTION_THRESHOLD`) MINUS whatever has already been promoted -
    see the module docstring on why that subtraction is not optional. An entry
    is "already promoted" when some AgentMemory row's `source_journal_id`
    already points at it; querying that column is cheaper and more honest
    than adding a status flag to journal_entries, which would be a second
    place to record a fact this column already carries.

    `agent_id=None` scopes to every agent, matching
    `journal.promotion_candidates()`'s own default - the future consolidation
    job runs this per session, not per agent, and a caller that wants one
    agent passes it explicitly.

    Returns the newly created rows only. An entry that was skipped because it
    was already promoted contributes nothing to this list - the caller cannot
    tell "already handled" from "did not qualify" from this return value
    alone, which is acceptable here because neither case has an action left
    to take; if that distinction is ever needed, a caller can compare against
    a fresh `journal.promotion_candidates()` call itself.
    """
    candidates = journal_svc.promotion_candidates(db, agent_id=agent_id)
    if not candidates:
        return []

    already_promoted = set(
        db.execute(
            select(AgentMemory.source_journal_id).where(
                AgentMemory.source_journal_id.in_([c.id for c in candidates])
            )
        )
        .scalars()
        .all()
    )

    created: list[AgentMemory] = []
    for entry in candidates:
        if entry.id in already_promoted:
            continue
        # DWB-637: DEFER, do not raise and do not write without an origin.
        #
        # This runs from the session-start consolidation pass, which has no
        # caller to answer and must not block. Nothing is lost by skipping: the
        # journal entry stays exactly where it is, `already_promoted` is
        # recomputed from `source_journal_id` on every pass, so this candidate
        # is proposed again unchanged by the next pass that has a session. A
        # deferred promotion is recoverable; a CORE row that cannot be scored
        # is not.
        #
        # Scoped per entry rather than once per call because this function's
        # default scope is every agent, and agents on different projects have
        # different sessions - a single check would read one project's state
        # and apply it to another's.
        agent = db.get(Agent, entry.agent_id)
        if agent is None or agent.project_id is None:
            continue
        if (
            memory_origin.deferrable_session_origin(db, project_id=agent.project_id)
            is None
        ):
            continue
        created.append(
            promote_to_core(
                db,
                agent_id=entry.agent_id,
                body=entry.body,
                source_journal_id=entry.id,
            )
        )
    return created
