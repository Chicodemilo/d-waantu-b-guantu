# Path: app/schemas/memory_score.py
# File: memory_score.py
# Created: 2026-09-29 (DWB-585)
# Purpose: Pydantic schemas for GET /api/agents/{id}/memory/scored - the
#          derived score, the band, and the demote / evict / promote lists.
# Caller: app/routers/agents.py
# Callees: pydantic
# Data In: dicts from app/services/memory_score
# Data Out: ScoredMemoryEntry, ScoredMemoryResponse
# Last Modified: 2026-09-30 (DWB-610: ScoredMemoryEntry carries `body`, so context
#                assembly has one read path for score + content instead of two)

from pydantic import BaseModel


class ScoredMemoryEntry(BaseModel):
    """One memory with its DERIVED score.

    `score` and `band` are computed at read time and are NOT columns. If either
    ever becomes a column, the guards in tests/test_memory_score_dwb585.py fail
    on purpose.

    `scored` is False for a row the curve does not apply to, and `reason` says
    which case it is: an untiered `raw` row awaiting consolidation, or a row
    with no session origin to count from. Both are normal states rather than
    errors, and both are excluded from every candidate list. They are reported
    rather than dropped, because a memory that silently vanishes from the list
    an agent reads is worse than one that appears with a stated reason.
    """

    id: int
    tier: str
    body: str
    context_key: str | None
    fired_count: int
    scored: bool
    reason: str | None
    sessions_since_reinforced: int | None
    score: int | None
    band: str | None


class ScoredMemoryResponse(BaseModel):
    """GET /api/agents/{id}/memory/scored.

    `computed` DISTINGUISHES "NOTHING TO DO" FROM "NOTHING RAN", and that is a
    requirement rather than a nicety. Three empty lists are the correct answer
    for a tidy agent in human_memory mode AND the answer for a project that
    never enabled the mode at all, and those are opposite facts. `computed:
    true` with empty lists is the first; `computed: false` plus a `reason` is
    the second.

    The lists carry memory ids for `demote` and `evict`, and JOURNAL entry ids
    for `promote`. They are different tables on purpose: promotion in this
    response means an entry reached for often enough that it should stop being
    a story and become a lesson (spec section 5), not the scar-to-CORE
    promotion of section 2, which needs recurrence evidence nothing records and
    which section 7 hard rule 5 keeps in human hands regardless.
    """

    agent_id: int
    computed: bool
    reason: str | None = None
    memory_mode: str | None = None
    entries: list[ScoredMemoryEntry]
    demote: list[int]
    evict: list[int]
    promote: list[int]
