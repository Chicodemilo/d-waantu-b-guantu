# Path: app/schemas/journal.py
# File: journal.py
# Created: 2026-09-29 (DWB-587)
# Purpose: Pydantic schemas for the human_memory journal - POST /api/journal
#          and the filtered GET /api/journal search result.
# Caller: app/routers/journal.py
# Callees: pydantic, app/services/journal (PROMOTION_THRESHOLD)
# Data In: JSON request body
# Data Out: JournalEntryCreate, JournalEntryRead, JournalSearchResponse
# Last Modified: 2026-09-29 (DWB-587)

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from app.services.journal import PROMOTION_THRESHOLD


class JournalEntryCreate(BaseModel):
    """POST /api/journal body (DWB-587).

    The section 4 moment-tags (cost, caught_by, surprised) are deliberately NOT
    on this body. DWB-584 moved them onto agent_memories, because what reads
    them reads memories: section 2 gates the SCAN on `cost`, and the SCAN runs
    over scars. The journal keeps `tags`, which is what section 5's retrieval
    ("tags + date + term") queries.

    VOICE RULE, documented rather than validated. Spec section 5: the literal
    "Dear Diary" prefix was dropped (charming once, noise on the two hundredth
    entry, and it makes the first line carry no information), but the instinct
    survives - "write like a person who was there, not an incident report
    written for review. A sanitized entry is a useless entry, because the value
    is the reasoning that felt correct and was not."

    It is not enforced because it cannot be: no validator can tell a candid
    account from a sanitized one, and a check that pretended to would just teach
    writers the shape that passes.
    """

    agent_id: int
    body: str
    tags: list[str] | None = None


class JournalEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    dwb_session_id: int | None
    entered_at: datetime
    # DWB-605: the memory's ORIGINAL date, distinct from entered_at. Equal to
    # entered_at for anything a session journals directly; only diverges for
    # an entry DWB-607's eviction journals on a memory's way out of
    # agent_memories, where the memory was created well before this entry was.
    created_at: datetime
    tags: list[str] | None
    # The count AFTER this retrieval, when this entry came back from a search.
    # Permanent and never decaying (spec section 5: the score is transient, the
    # count is permanent).
    retrieval_count: int
    body: str

    @computed_field
    @property
    def promotion_candidate(self) -> bool:
        """At PROMOTION_THRESHOLD retrievals an entry stops being a story and
        becomes a rule (spec section 5), and belongs in DWB-585's promote[].

        Derived, never stored, for the same reason the score is: a stored flag
        is a second authoritative copy of a fact the count already carries, and
        it would need rewriting on every retrieval.
        """
        return self.retrieval_count >= PROMOTION_THRESHOLD


class JournalSearchResponse(BaseModel):
    """GET /api/journal result.

    `status` and `filters_applied` are here so an empty `entries` list is
    readable. "Ran with these filters and matched nothing" is a different fact
    from "was truncated" and from "errored", and a bare empty list says none of
    them - which is the ambiguity that hid a broken retrieval path for a whole
    sprint on the nodes lane.
    """

    status: Literal["complete", "truncated"]
    count: int
    total_matched: int
    filters_applied: list[str]
    entries: list[JournalEntryRead]
