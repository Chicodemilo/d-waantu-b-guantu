# Path: app/schemas/agent_memory.py
# File: agent_memory.py
# Created: 2026-09-29 (DWB-586)
# Purpose: Pydantic schemas for the raw memory write - POST /api/agents/{id}/memories
# Caller: app/routers/agents.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: RawMemoryCreate, RawMemoryResponse
# Last Modified: 2026-09-29 (DWB-586: moment-tags moved onto the memory row)

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RawMemoryCreate(BaseModel):
    """POST /api/agents/{agent_id}/memories body (DWB-586).

    body: the memory, as written in the moment. Required, non-empty.
    context_key: what this is bound TO, when the writer already knows. Consolidation
                 is what decides whether a row is context-bound; naming the context
                 at write time is recording a fact, not making that judgment.
    cost / caught_by / surprised: section 4's moment-tags - what the moment knows
                 and cannot later be reconstructed. All optional; section 4's rule
                 is to tag only what the moment knows, so an untagged memory is the
                 normal case. `caught_by` earns its place through one query:
                 everything the human had to catch is a map of where the agent's
                 own checks do not look.
    tier: accepted ONLY so that a request naming one can be refused with a reason.
          Spec section 4 rules out tiering at write time and section 7 hard rule 5
          rules out CORE outright. Dropping the field from the schema would make a
          tiering attempt silently succeed-as-raw, which is worse than a 400: the
          caller would believe it had tiered something.
    """

    body: str
    context_key: str | None = None
    cost: Literal["none", "low", "high"] | None = None
    caught_by: Literal["me", "worker", "human", "ci"] | None = None
    # Tri-state: True, False, and "nobody said". None is not False - section 1
    # makes prediction error the driver of encoding strength, so the difference
    # between "was not surprised" and "was never asked" is a real one.
    surprised: bool | None = None
    tier: str | None = None


class RawMemoryResponse(BaseModel):
    """The written row, plus what the session lookup found.

    `session_state` exists because `created_session_id: null` on its own is
    ambiguous - it cannot distinguish "no session was open" from "we never
    looked". The two are different facts and only one of them is fine. Values:
    `open` (id stamped) and `none_open` (write accepted, id null).
    """

    id: int
    agent_id: int
    tier: str
    body: str
    context_key: str | None
    cost: str | None
    caught_by: str | None
    surprised: bool | None
    created_session_id: int | None
    session_state: str
    fired_count: int
    created_at: datetime


class MemoryWithdrawRequest(BaseModel):
    """DWB-626: retract one of your own memory rows.

    `reason` is optional and free text. It is appended to the JOURNALED body
    rather than added to `tags`, because tags are the controlled vocabulary the
    journal search filters on and a free-text reason in there would make every
    retraction its own unsearchable tag.
    """

    reason: str | None = None


class MemoryWithdrawResponse(BaseModel):
    """What was withdrawn, and WHERE IT WENT.

    `journal_entry_id` is the load-bearing field. A withdrawal that could not
    say where the content landed would be indistinguishable from a deletion,
    and the retraction is recoverable precisely because this id exists.
    """

    memory_id: int
    agent_id: int
    tier: str
    body: str
    context_key: str | None
    withdrawn: bool
    journal_entry_id: int
    journal_tags: list[str]
    reason: str | None
