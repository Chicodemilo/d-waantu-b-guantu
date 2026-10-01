# Path: app/services/raw_memory.py
# File: raw_memory.py
# Created: 2026-09-29 (DWB-586)
# Purpose: The RAW memory write for human_memory mode. Appends one untiered
#          agent_memories row, stamps the open DWB session, and refuses to
#          mint a CORE memory.
# Caller: app/routers/agents.py (POST /api/agents/{id}/memories)
# Callees: app/services/dwb_session.get_active_session,
#          app/services/agent._record_memory_write, app/models/agent_memory
# Data In: agent_id, body, optional context_key, the section 4 moment-tags,
#          optional tier (refused)
# Data Out: dict describing the written row, including session_state
# Last Modified: 2026-09-29 (DWB-586)

"""Raw, untiered memory writes (spec section 4).

NOT app/services/agent_memory.py, which is the memory-DIRECTORY scaffolder for
stock mode and predates this feature by four months. The names are close enough
to matter: this module writes ROWS into `agent_memories`, that one writes FILES
into `.dwb/memory/`.

Spec `docs/human_memory_spec.md` section 4, verbatim: "Append RAW and unsorted
during a session. No tiering. Tiering in the moment rubber-stamps in-the-moment
salience, which is the judgment consolidation exists to make."

So this module writes ONE tier and one only: `raw`. Tier is not a caller field.
Consolidation (DWB-588) is what moves a row off `raw`, and CORE is reachable
from neither: section 7 hard rule 5 puts it behind a human ruling or logged
cross-context promotion evidence.

Two things here are less obvious than they look.

**`raw` is written as an enum value, never as NULL.** That is DWB-584's ruling,
not a local choice: NULL in this schema already means "we do not know", and an
untiered row is a known state a writer chose. It also forces DWB-585's scoring
query to NAME `raw` in order to exclude it, where a nullable column would let an
IS NOT NULL drop those rows silently.

**The three moment-tags live on the MEMORY, not the journal.** Spec section 6
DWB-632 NOTE ON "CONSOLIDATION TIERS IT LATER". That sentence was false from
the day it was written until DWB-632: nothing anywhere moved a row out of
`raw`, so every row this module wrote was permanently unscoreable and never
rendered. It is true now - `memory_consolidate.tier_raw_memories` runs at
session start and judges these rows from the moment-tags below. If you are
reading this because a raw row is still untiered, check that consolidation is
reaching this agent before assuming the rule is wrong.

as amended 2026-09-29 (DWB-584). Sections 4 and 6 disagreed about where `cost`,
`caught_by` and `surprised` belonged; the tie was broken by asking what READS
each one, and all three are read against memories - section 2 gates the SCAN on
`cost`, and the SCAN runs over scars, which are memory rows.

**A write with no open session is ACCEPTED.** The alternative is losing the
lesson because the bookkeeping was not ready, and section 4's whole point is
that encoding is cheap and unconditional. The response says which happened
through a named `session_state` rather than leaving the caller to infer it from
a null id - an empty field cannot distinguish "no session was open" from "we
never looked".
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import (
    AgentMemory,
    MemoryCaughtBy,
    MemoryCost,
    MemoryTier,
)
from app.models.project import Project
from app.services import dwb_session as session_svc
from app.services.agent import _record_memory_write

# What the session lookup found. Named values, not a bare null id, for the same
# reason node_retrieval names its four: an empty field is ambiguous between
# "nothing was there" and "nobody looked", and that ambiguity is the bug behind
# the bug. Two values here because there are exactly two outcomes - the lookup
# is a single indexed read that cannot be truncated and does not fail softly.
SESSION_OPEN = "open"  # created_session_id is that session's id
SESSION_NONE_OPEN = "none_open"  # accepted anyway; created_session_id is null


class RawMemoryWriteError(Exception):
    """Raised by append_raw_memory; the router maps `code` to a status."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def append_raw_memory(
    db: Session,
    *,
    agent_id: int,
    body: str,
    context_key: str | None = None,
    cost: str | None = None,
    caught_by: str | None = None,
    surprised: bool | None = None,
    tier: str | None = None,
) -> dict:
    """Append one untiered memory row for `agent_id`.

    `tier` is accepted only so a request naming a tier can be REFUSED with a
    reason. There is no value it may hold: section 7 hard rule 5 rules CORE out
    entirely, and section 4 rules out the rest by ruling out tiering at write
    time. Silently ignoring the field would let a caller believe it had tiered
    something.

    `cost`, `caught_by` and `surprised` are section 4's moment-tags: what the
    moment knows and cannot later be reconstructed. All three are optional,
    because section 4's rule is to tag only what the moment knows - an untagged
    memory is the normal case, not a defect. `surprised` is tri-state: True,
    False and "nobody said" are three different facts, so None is not False.

    Stamps `agents.last_memory_write_at` through the same helper the stock
    memory writes use, so the DWB-519 write-on-close gate proves participation
    for a human_memory project with no mode-aware branch (see DWB-589).

    Raises RawMemoryWriteError with codes:
      - agent_not_found, agent_unscoped, project_not_found
      - empty_body
      - core_forbidden     (tier=core specifically, so the refusal cites the rule)
      - tier_not_settable  (any other tier)
    """
    if tier is not None:
        # CORE gets its own code and its own sentence. The generic refusal is
        # true for it as well, but a caller reaching for `core` is reaching for
        # the one tier with a written rule behind it, and a refusal that does
        # not quote the rule teaches nothing.
        if tier == MemoryTier.core.value:
            raise RawMemoryWriteError(
                "core_forbidden",
                "tier 'core' cannot be set by this endpoint. Spec section 7 hard "
                "rule 5: CORE is never touched by automatic consolidation - only a "
                "human retires a ruled entry, and only logged cross-context "
                "evidence adds a graduated one. A raw write is neither, so there "
                "is no request shape that reaches CORE from here.",
            )
        raise RawMemoryWriteError(
            "tier_not_settable",
            f"tier '{tier}' cannot be set at write time. Spec section 4: append RAW "
            "and unsorted during a session, because tiering in the moment "
            "rubber-stamps in-the-moment salience, which is the judgment "
            "consolidation exists to make. Every row this endpoint writes is "
            f"'{MemoryTier.raw.value}'; consolidation tiers it at the next "
            "session start (DWB-632: memory_consolidate.tier_raw_memories).",
        )

    if not body or not body.strip():
        raise RawMemoryWriteError(
            "empty_body", "body is required and cannot be empty or whitespace-only"
        )

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise RawMemoryWriteError("agent_not_found", f"agent id {agent_id} not found")
    if agent.project_id is None:
        raise RawMemoryWriteError(
            "agent_unscoped",
            f"agent id {agent_id} has no project_id - cannot resolve the open session",
        )
    project = db.get(Project, agent.project_id)
    if project is None:
        raise RawMemoryWriteError(
            "project_not_found",
            f"agent id {agent_id} references project {agent.project_id} which is missing",
        )

    active = session_svc.get_active_session(db, project.id)
    session_state = SESSION_OPEN if active is not None else SESSION_NONE_OPEN

    row = AgentMemory(
        agent_id=agent.id,
        tier=MemoryTier.raw,
        body=body,
        context_key=context_key,
        cost=MemoryCost(cost) if cost is not None else None,
        caught_by=MemoryCaughtBy(caught_by) if caught_by is not None else None,
        surprised=surprised,
        created_session_id=active.id if active is not None else None,
    )
    db.add(row)
    db.flush()

    # Same stamp the stock writes take. _record_memory_write commits, which also
    # persists the row flushed above; that is the single commit for this call.
    _record_memory_write(db, agent, datetime.now(timezone.utc))

    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "tier": row.tier.value,
        "body": row.body,
        "context_key": row.context_key,
        "cost": row.cost.value if row.cost is not None else None,
        "caught_by": row.caught_by.value if row.caught_by is not None else None,
        "surprised": row.surprised,
        "created_session_id": row.created_session_id,
        "session_state": session_state,
        "fired_count": row.fired_count,
        "created_at": row.created_at,
    }
