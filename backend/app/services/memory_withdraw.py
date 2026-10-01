# Path: app/services/memory_withdraw.py
# File: memory_withdraw.py
# Created: 2026-10-01 (DWB-626)
# Purpose: WITHDRAWAL - the owning agent retracts one of its own memory rows.
#          The policy half (who may, and what refuses); the mechanism half lives
#          in memory_removal.journal_and_remove.
# Caller: app/routers/agents.py (POST /agents/{id}/memories/{mid}/withdraw)
# Callees: app/services/memory_removal, app/models/agent_memory, app/models/agent
# Data In: db Session, owning agent id, memory id, acting agent id, reason
# Data Out: a dict describing what was withdrawn and where it went
# Last Modified: 2026-10-01 (DWB-626)

"""The first way anything has ever left agent_memories by choice.

Before this, the entire memory surface was GET memory, GET scored, POST append,
POST compact, POST condense, POST scaffold-memory, POST memories. Nothing
edited or retracted a row, ever, so a wrong lesson was permanent and the party
best placed to notice - the agent that wrote it - was the party with no way to
act.

That is not hypothetical. One agent carries two scars that contradict each
other on the same question, neither marked as superseding the other, both
resting where they no longer decay. Three consultations promotes either one to
CORE, which never decays at all, so whichever it reaches for first wins
permanently. And a duplicate row was created by probing a write endpoint within
an hour of the team establishing that nothing could remove one.

ONE MOVEMENT PER FILE, which is why this is not a function inside
memory_removal.py. Removal is the MECHANISM and has three callers with three
different triggers (a withdrawal, a WORKING floor, a concluded scar context).
Withdrawal is one of those triggers and owns only the question of who may pull
it. Keeping the trigger out of the mechanism is the same reason
memory_scar_conclude.py is a sibling FILE of memory_evict.py rather than a
second function inside it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory
from app.services import memory_removal

# The controlled vocabulary this movement stamps on what it journals, so a human
# reading the journal later can see WHY an entry arrived without joining back to
# anything. Mirrors memory_evict.EVICTION_TAGS and memory_decide.SKIP_TAGS.
WITHDRAWAL_TAGS = ["withdrawn", "retracted-by-owner"]


class WithdrawError(Exception):
    """Raised when a withdrawal is refused. Carries a code and a detail."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def withdraw_memory(
    db: Session,
    *,
    agent_id: int,
    memory_id: int,
    acting_agent_id: int | None,
    reason: str | None = None,
) -> dict:
    """Retract one memory row belonging to `agent_id`.

    OWNERSHIP IS THE WHOLE POLICY (Archie's ruling, DWB-626): the owning agent,
    and nobody else. The ticket's own argument is that the deciding agent is the
    only party with the context to recognise a wrong call, and an agent
    withdrawing ANOTHER agent's memory is a different feature with different
    risks - it does not get smuggled in through a permissive check here.

    ON "PLUS THE HUMAN", AND THIS IS A GAP RATHER THAN A DECISION: there is no
    human actor at this API. Nothing anywhere distinguishes a human caller from
    an agent one - `award_human_score`, the closest precedent, authenticates
    nothing. So the human acts through the owner's id, exactly as the existing
    human-facing commands do, and this function cannot tell the two apart. A
    distinct human identity is a separate ticket; inventing an auth scheme here
    to satisfy one clause would be a security decision made in passing.

    Does not commit; the router owns the transaction.
    """
    memory = db.get(AgentMemory, memory_id)
    if memory is None:
        raise WithdrawError("memory_not_found", f"memory id {memory_id} not found")

    # Checked BEFORE ownership, so a caller aiming at the wrong agent gets told
    # which fact is wrong rather than being told it does not own a row that was
    # never in that agent's memory in the first place.
    if memory.agent_id != agent_id:
        raise WithdrawError(
            "memory_not_on_agent",
            f"memory {memory_id} belongs to agent {memory.agent_id}, "
            f"not agent {agent_id}",
        )

    if acting_agent_id is None:
        raise WithdrawError(
            "actor_required",
            "X-Agent-ID is required: a withdrawal is an act by a named owner, "
            "and an unattributed retraction is indistinguishable from a bug.",
        )
    if acting_agent_id != memory.agent_id:
        actor = db.get(Agent, acting_agent_id)
        actor_name = actor.name if actor is not None else f"id {acting_agent_id}"
        raise WithdrawError(
            "not_owner",
            f"{actor_name} cannot withdraw a memory belonging to agent "
            f"{memory.agent_id}. Only the owning agent may retract its own "
            "memory: the owner is the party with the context to know the "
            "lesson is wrong, and withdrawing someone else's is a different "
            "operation with different risks.",
        )

    # Read what we need BEFORE the row is gone. After journal_and_remove the
    # instance is deleted and attribute access on it is no longer answerable.
    snapshot = {
        "memory_id": memory.id,
        "agent_id": memory.agent_id,
        "tier": memory.tier.value,
        "body": memory.body,
        "context_key": memory.context_key,
    }

    entry = memory_removal.journal_and_remove(
        db, memory, tags=WITHDRAWAL_TAGS, reason=reason
    )

    return {
        **snapshot,
        "withdrawn": True,
        # The journal id is the whole point of the response: a withdrawal that
        # could not say where the content went would be indistinguishable from
        # a deletion, and the retraction is recoverable precisely because this
        # id exists.
        "journal_entry_id": entry.id,
        "journal_tags": list(WITHDRAWAL_TAGS),
        "reason": reason,
    }
