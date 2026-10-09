# Path: app/services/memory_demote.py
# File: memory_demote.py
# Created: 2026-10-09 (DWB-665)
# Purpose: DEMOTION - the way back off CORE. The only path in the application
#          that moves a row's tier OFF `core`, deliberate and attributable,
#          mirroring memory_promote.promote_to_core in reverse.
# Caller: app/routers/agents.py (POST /agents/{id}/memories/{mid}/demote)
# Callees: app/models/agent_memory, app/models/agent, app/services/journal
# Data In: db Session, owning agent id, memory id, acting agent id, target
#          tier, a required reason
# Data Out: a dict describing the movement, including the journal entry id that
#           records it
# Last Modified: 2026-10-09 (DWB-665)

"""CORE was a one-way door, and that is what made a mistake permanent.

`memory_promote.promote_to_core` is the only write site for `tier =
MemoryTier.core`, and before this module nothing anywhere wrote `core` to any
other tier. There was no `demote_from_core`, no reverse of `promote_to_core`,
and no route that set a tier directly. So a row that reached CORE by mistake -
a false consultation fire (DWB-644), a bad ruling, any other path into
`promote_to_core` - stayed there.

IT COULD NOT EVEN BE NOMINATED. CORE's curve is flat at 10 in every bucket
(`memory_score._CURVE`), and `GET /memory/scored`'s demote / evict / promote
lists populate from the derived SCORE BAND. A CORE row scores 10, so it lands
in `full_text` forever and can never appear in any candidate list however wrong
its tier is. The ruling had nowhere to write and the row had no way to surface.

LIVE WHEN THIS WAS WRITTEN: IND holds 39 rows mis-tiered into CORE. THIS
TICKET DOES NOT REPAIR THEM and must not be read as having done so - DWB-665
criterion 4 scopes that out explicitly, and re-tiering real rows is a ruling
per row rather than a sweep. This module is the mechanism those rulings will
need.

WHY DEMOTION MATTERS MORE AFTER DWB-668, NOT LESS. While CORE was excluded
from `consult_scars`, a mis-promoted row was inert: wrong, permanent, and
unreachable, so it misled nobody. DWB-668 put CORE into the search population.
A mis-promoted row is now a LIVE JUNK ROUTE that can be recalled into an
agent's context at the top band, by a tier that never decays. Getting out
became the difference between a filing error and a served one.

OWNER-ONLY, SAME POLICY AS WITHDRAWAL AND RE-KEYWORDING. The owning agent and
nobody else. Three reasons rather than one, because deviating from the
precedent would have needed a better one than convenience:

  - It is the policy every other mutation of `agent_memories` already uses
    (`memory_withdraw`, `memory_fill.rekey_memory`). A second, more permissive
    rule for a third mutation is how a surface ends up with two answers to
    "who may change my memory".
  - The owner is the party with the context to know the tier is wrong, which is
    DWB-626's argument for withdrawal and applies here unchanged.
  - A cross-agent tier write destroys the one thing that still carries
    provenance. When several agents write under one id, `agent_id` stops
    meaning "who thought this"; a demotion recorded against the owner but
    decided by someone else would do the same to `tier`.

ON "PLUS THE HUMAN": there is no human actor at this API and nothing here can
distinguish a human caller from an agent one, exactly as `memory_withdraw`
records. The human acts through the owner's id. That is a gap in the API, not
a decision made here.

WHAT THIS DOES NOT DO, STATED BECAUSE THE ABSENCES ARE DELIBERATE:

  - IT DOES NOT RESET THE DECAY CLOCK. A row demoted after 400 elapsed sessions
    lands on the scar or working curve at its floor, immediately. That is the
    honest number: the clock records experience that really happened, and
    resetting it would hand a mis-promoted row a fresh full-strength life as a
    reward for having been wrong. Ruled by Archie, 2026-10-09.
  - IT DOES NOT RESTORE `context_key`. Promotion used to clear it. DWB-665
    stopped that going forward (see `promote_to_core`), but rows promoted
    before today have already lost theirs and there is no backup column.
    Reconstructing a value that was deliberately discarded would be guessing,
    so a row demoted today may return as a scar with `context_key` NULL, which
    `memory_scan` already treats as "not named yet" rather than as an error.
  - IT DOES NOT TOUCH `fired_count`. The recall history is a fact about what
    happened, not a property of the tier, and a demotion that silently reset it
    would destroy the only evidence anyone has about whether the row was ever
    used - which, after DWB-668, is the evidence a future demotion ruling will
    rest on.
  - IT IS NOT AUTOMATIC AND NOTHING IN THE DECAY MACHINERY CALLS IT. DWB-665
    criterion 2: CORE is deliberately the tier an algorithm may not
    second-guess a human out of. There is no scan, no sweep and no scheduled
    job that reaches this function; it has exactly one caller and that caller
    is an HTTP route with a required reason.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.services import journal as journal_svc

# Where a row may land. `core` is excluded because that is the tier being left,
# and `raw` because it is the UNTIERED state a row is written in before
# consolidation has judged it - a demotion is a judgment, so landing one in
# `raw` would claim the opposite of what just happened, and `raw` rows are
# excluded from scoring entirely (`memory_score` reports them `untiered`), so
# it would swap one unreachable state for another.
DEMOTABLE_TIERS: tuple[MemoryTier, ...] = (MemoryTier.scar, MemoryTier.working)

DEMOTION_TAGS = ("demoted", "tier-ruling")


class DemoteError(Exception):
    """Raised by this module; the router maps `code` to a status, the same
    pattern `memory_withdraw.WithdrawError` and `memory_fill.MemoryFillError`
    already use."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def demote_from_core(
    db: Session,
    *,
    agent_id: int,
    memory_id: int,
    acting_agent_id: int | None,
    to_tier: MemoryTier | str,
    reason: str,
) -> dict:
    """Move one CORE row to `scar` or `working`. The only path off CORE.

    Every refusal below happens BEFORE any assignment, so a request that is
    going to be refused leaves the row untouched even in the session's identity
    map.

    Does not commit; the router owns the transaction, same convention as every
    other service in this lane.
    """
    memory = db.get(AgentMemory, memory_id)
    if memory is None:
        raise DemoteError("memory_not_found", f"memory id {memory_id} not found")

    # Checked before ownership, so a caller aiming at the wrong agent is told
    # which fact is wrong rather than that it does not own a row that was never
    # in that agent's memory. Same ordering memory_withdraw settled.
    if memory.agent_id != agent_id:
        raise DemoteError(
            "memory_not_on_agent",
            f"memory {memory_id} belongs to agent {memory.agent_id}, not agent "
            f"{agent_id}",
        )

    if acting_agent_id is None:
        raise DemoteError(
            "actor_required",
            "X-Agent-ID is required: a demotion is a tier RULING by a named "
            "owner, and an unattributed one is indistinguishable from a bug in "
            "the consolidation machinery - which is exactly what this movement "
            "must never look like.",
        )
    if acting_agent_id != memory.agent_id:
        actor = db.get(Agent, acting_agent_id)
        actor_name = actor.name if actor is not None else f"id {acting_agent_id}"
        raise DemoteError(
            "not_owner",
            f"{actor_name} cannot demote a memory belonging to agent "
            f"{memory.agent_id}. Only the owning agent may re-tier its own "
            "memory, the same policy withdrawal and re-keywording already use: "
            "the owner is the party with the context to know the tier is "
            "wrong, and a cross-agent tier write destroys the provenance the "
            "tier is supposed to carry.",
        )

    if memory.tier != MemoryTier.core:
        raise DemoteError(
            "not_core",
            f"memory {memory_id} is tier {memory.tier.value}, not core. This "
            "movement exists only to open the one door that had no way back; "
            "every other tier already moves under consolidation, and a general "
            "set-the-tier route would reintroduce exactly the agent-chooses-"
            "its-own-tier problem `memory_decide` refuses.",
        )

    target = MemoryTier(to_tier) if not isinstance(to_tier, MemoryTier) else to_tier
    if target not in DEMOTABLE_TIERS:
        raise DemoteError(
            "invalid_target_tier",
            f"cannot demote to {target.value}. A demotion lands in "
            f"{' or '.join(t.value for t in DEMOTABLE_TIERS)}: `core` is the "
            "tier being left, and `raw` is the untiered state a row waits in "
            "BEFORE a judgment - landing a judgment there would claim the "
            "opposite of what just happened and the row would stop being "
            "scored at all.",
        )

    if not reason or not reason.strip():
        raise DemoteError(
            "reason_required",
            "a reason is required and cannot be empty. A demotion is the only "
            "movement that overturns a promotion the system made on evidence, "
            "so the record has to say what the human knew that the evidence "
            "did not. 'Mis-promoted by a false consultation fire' and 'the "
            "context this was bound to ended years ago' are reasons; a blank "
            "is a tier change nobody can audit.",
        )

    previous_tier = memory.tier

    # THE JOURNAL ENTRY IS WRITTEN BEFORE THE TIER MOVES, deliberately. If the
    # transaction fails between the two, the surviving state is a journal entry
    # describing a demotion that did not happen - which is loud and correctable.
    # The other order survives as a demoted row with no record of who ruled or
    # why, which is indistinguishable from the consolidation machinery having
    # done it, and that is the one thing criterion 2 forbids.
    entry = journal_svc.create_entry(
        db,
        agent_id=memory.agent_id,
        body=(
            f"Demoted memory {memory.id} from {previous_tier.value} to "
            f"{target.value}. Ruled by agent {acting_agent_id}.\n\n"
            f"Reason: {reason.strip()}\n\n"
            f"The decay clock was NOT reset: this row keeps "
            f"created_session_id={memory.created_session_id} and "
            f"last_reinforced_session_id={memory.last_reinforced_session_id}, "
            f"so it lands on the {target.value} curve at whatever its elapsed "
            f"sessions earn. fired_count ({memory.fired_count}) is untouched."
        ),
        tags=list(DEMOTION_TAGS),
    )

    memory.tier = target
    db.flush()

    return {
        "memory_id": memory.id,
        "agent_id": memory.agent_id,
        "previous_tier": previous_tier.value,
        "tier": target.value,
        "reason": reason.strip(),
        "ruled_by_agent_id": acting_agent_id,
        # The clock and the recall history are returned rather than described,
        # because "we did not touch them" is a claim and these are the values.
        "created_session_id": memory.created_session_id,
        "last_reinforced_session_id": memory.last_reinforced_session_id,
        "fired_count": memory.fired_count,
        "context_key": memory.context_key,
        "journal_entry_id": entry.id,
        "journal_tags": list(DEMOTION_TAGS),
    }
