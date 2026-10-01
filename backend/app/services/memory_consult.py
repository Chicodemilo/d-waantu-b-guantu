# Path: app/services/memory_consult.py
# File: memory_consult.py
# Created: 2026-09-30 (DWB-603, redesigned per Miles's firing ruling)
# Purpose: The consultation Miles ruled into existence - "have I made this
#          scar producing error before? Outside of normal startup." The ONLY
#          write site for AgentMemory.fired_count. Requires a real term, same
#          discipline journal.search_entries already enforces, and fires only
#          the rows that MATCH.
# Caller: whatever ends up calling a deliberate consultation (settled with
#         Barry/Freddie: not spawn/SessionStart injection, not DWB-613's
#         dashboard - both call memory_score.scored_memory(), which is pure)
# Callees: app/models/agent_memory, app/services/memory_scan (SCAR_FAMILY)
# Data In: db Session, agent_id, a search term
# Data Out: dict {agent_id, term, count, entries: list[AgentMemory]} - matches
#           already carry the post-increment fired_count
# Last Modified: 2026-09-30 (DWB-603 cont'd)

"""Firing, moved to where Miles's ruling says it belongs.

THE RULING, VERBATIM: "Deploy doesn't count as a read. Reading is Oh have I
made this scar producing error before? Outside of normal startup." The
original DWB-603 put the write site inside `memory_score.scored_memory()`,
reasoning that `GET /memory/scored` was the only read path the store had. It
was wrong, and the audit that found it wrong found the actual seam: a read is
injection-shaped when it can be satisfied with NO QUESTION AT ALL.
`scored_memory()` can - it is "give me everything," no filter, nothing to
consult, which is exactly why it is called from BOTH spawn/SessionStart
injection and DWB-613's dashboard panel without either of those callers
needing to ask anything first. `journal.search_entries` never could: DWB-587
already refuses a filterless request, for an unrelated stated reason (the
journal must shrink while it may sprawl), but that same constraint happens to
be what makes a journal search a genuine consultation no matter what triggers
it. This module gives scars the equivalent: a search that cannot be asked with
no question in it.

WHY A SEPARATE MODULE RATHER THAN A FLAG ON `scored_memory()`. Barry's first
instinct was a `count_as_read` parameter, defaulting to fire. Archie's ruling
on that, which this module exists to honour: "a flag leaves firing reachable
from the injection path and relies on every future caller passing the right
value. Removing the call site makes injection... structurally incapable of
firing." A flag is a rule a caller can get wrong by omission; a call site that
does not exist cannot be gotten wrong at all. `scored_memory()` now contains
no code path that can ever touch `fired_count`, by construction, not by
convention.

TERM REQUIRED, NO BLANKET MATCH. Same reasoning as `journal.search_entries`'s
filter requirement, applied to the actual defect this module exists to avoid
repeating: a consultation with no term in it is a list wearing a consultation's
clothes, and would reopen exactly the hole this ticket closed. Refused the
same way journal refuses an unfiltered read.

ONLY A MATCH FIRES. Section 5's principle, carried over: a match is literal
evidence the agent has been here before (Archie's framing of Miles's own
words). A search that found nothing is not evidence of anything, so a scar
that was searched FOR and not found gets no increment - approaching the
question and getting a negative answer does not count as having asked it
successfully. Scoped to `memory_scan.SCAR_FAMILY` rather than a second
tier list of its own: there is exactly one definition in this codebase of
"what is a scar" and this module imports it rather than keeping a second one
that could drift from the first.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.agent_memory import AgentMemory
from app.services.memory_scan import SCAR_FAMILY


class ConsultError(Exception):
    """Raised by this module; the router (once one exists) maps `code` to a
    status, same pattern as every other service error class in this lane."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _fire(db: Session, memory_ids: list[int]) -> None:
    """THE ONLY WRITE SITE FOR `fired_count` IN THE APPLICATION.

    A single UPDATE, not a loop - same shape journal.py's own write site uses
    for its counter, for the same reason: one statement is what lets a guard
    test assert "exactly one write site" and mean it. `synchronize_session=
    "fetch"` expires the matching ORM objects, so a caller holding those rows
    (consult_scars does, immediately after this call) reads the POST-increment
    value rather than the stale one already in the session's identity map.
    """
    if not memory_ids:
        return
    db.execute(
        update(AgentMemory)
        .where(AgentMemory.id.in_(memory_ids))
        .values(fired_count=AgentMemory.fired_count + 1)
        .execution_options(synchronize_session="fetch")
    )


def consult_scars(db: Session, *, agent_id: int, term: str) -> dict:
    """The deliberate consultation: "have I made this scar producing error
    before?" Searches this agent's scars for `term`; every MATCH has its
    `fired_count` incremented, nothing else is touched.

    Refuses a blank or missing term the same way `journal.search_entries`
    refuses a filterless request - see the module docstring on why that
    refusal is the actual mechanism, not a formality borrowed from journal.py.

    Returns a dict rather than a bare list - `{agent_id, term, count,
    entries}` - mirroring `journal.search_entries`'s shape (DWB-612 pulls
    `result["count"]` and `[e.id for e in result["entries"]]` off that
    response today; this gives it the same two handles for scars without
    inventing a second response convention). No `status`/`truncated` field:
    unlike the journal, which can genuinely sprawl, there is no limit applied
    here to be truncated against, so every call is complete by construction;
    adding that field before anything needs it would be answering a question
    nobody is asking yet.

    `entries` carries the matched rows post-increment, same ordering
    `_fire`'s `synchronize_session="fetch"` already guarantees elsewhere in
    this lane: a caller reading `entries[i].fired_count` sees the value AFTER
    this call, not the one that was true when the search started.

    Does not commit; the caller owns the transaction, same convention as
    every other service function in this lane.
    """
    if not term or not term.strip():
        raise ConsultError(
            "term_required",
            "a consultation requires a real term - 'have I made this error "
            "before' is a question, and a blank term asks nothing. Supply "
            "what you suspect you have seen before.",
        )

    cleaned = term.strip()
    matches = list(
        db.execute(
            select(AgentMemory)
            .where(
                AgentMemory.agent_id == agent_id,
                AgentMemory.tier.in_(SCAR_FAMILY),
                AgentMemory.body.like(f"%{cleaned}%"),
            )
            .order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )

    _fire(db, [m.id for m in matches])
    db.flush()

    return {
        "agent_id": agent_id,
        "term": cleaned,
        "count": len(matches),
        "entries": matches,
    }
