# Path: app/services/context_scope.py
# File: context_scope.py
# Created: 2026-10-28 (DWB-704)
# Purpose: Refuse a memory write whose named scope cannot conclude. A scar is
#          supposed to leave the tier when its CONTEXT closes, so a context_key
#          that resolves to nothing is a binding the scan can never act on. The
#          gate uses `memory_scan`'s own resolvers rather than a second copy, so
#          what passes here is exactly what the scan will later resolve.
# Caller: app/services/raw_memory.append_raw_memory (the lesson write gate)
# Callees: app/services/memory_scan (_resolve_ticket, _resolve_epic,
#          _TICKET_CLOSED_STATUSES) - READ ONLY
# Data In: the author's context_key and broad-scope declaration, plus the
#          agent whose project the key is resolved against
# Data Out: nothing on success; ContextScopeUnresolvable on refusal
# Last Modified: 2026-10-28 (DWB-704 correction: the measured block went stale
#                the same day DWB-710 landed, so the figures are re-measured and
#                now state what would invalidate them rather than when they were
#                taken; the volatile count is out of the refusal text)

"""The write-time half of the context-liveness contract (DWB-704).

THE DEFECT THIS CLOSES. The context-liveness design is built and correct and
has never concluded a single scar in its existence.

WHAT WOULD INVALIDATE THE FIGURES BELOW, stated instead of a date, because the
first version of this paragraph carried a date and went stale four hours later
ON THE SAME DAY. They are counts over `agent_memories` rows in SCAR_FAMILY, and
they move when: a scar is written or retiered; anything rewrites `context_key`
in bulk; or a ticket or epic named by a key changes status. The second has
already happened once - DWB-710 moved 380 adopted heading paths out of
`context_key` into `adopted_from_heading` - and it changed every number here.
Re-derive by running `scan_context` over SCAR_FAMILY; do not quote these.

    scar-family rows                   870
    with a context_key                  45   (424 before DWB-710)
    distinct values                     41
    containing a ticket key              1
    scan_context verdicts              829 still_active, 41 unresolvable,
                                       0 declared_broad, 0 FINISHED
    carrying adopted_from_heading      380

TWO OF THOSE LINES ARE STANDING CLAIMS AND THE REST ARE A SNAPSHOT.

THE FIRST: zero scars have concluded, before DWB-710 or after. That is the
reason this module exists.

THE SECOND, AND IT IS THE SHAPE THIS MODULE WAS WRITTEN TO REFUSE, SITTING IN
THE MODULE'S OWN VERDICT. Of the 829 `still_active` verdicts, 825 are rows with
NO `context_key` at all; only 4 are keys that resolved to live work. A row with
no scope recorded is NOT a row whose scope is alive. The verdict is the SAFE
answer - it declines to delete, which is right - but the NAME states something
the data does not support, and it is the same move this file condemns two
paragraphs down: reading "I could not resolve this" as a positive claim about
the scope. That reading, in a different branch, promoted 381 of 455 rows into
the tier only a human may grant. NOTHING MAY EVER READ `still_active` AS
EVIDENCE THAT A SCOPE EXISTS.

THE MECHANISM IS NOT BROKEN, IT IS STARVED, and that was established by driving
a real ticket key through the live write route: the row reported `still_active`
while its ticket was open and `finished` the moment the ticket closed. Every
part of the lane works except that nothing ever feeds it a scope it can resolve.

WHERE THE HEADING PATHS CAME FROM, because it decides what this gate can and
cannot fix. Two write paths set `context_key` and they are disjoint.
`memory_decide.decide` set it to `" / ".join(heading_path)` while adopting a
markdown memory.md, and that path produced every one of the heading-shaped
values - `'ABOVE THE FOLD'`, `'Agreement is not verification'`. DWB-710 has
since moved all 380 of those out of the scope column entirely. This gate never
touched them and was never the repair for them; it governs what arrives from
now on.

WHAT THIS GATE REFUSES IN PRACTICE, AND THE SENTENCE THAT USED TO BE HERE. The
first version read "THIS GATE REFUSES NOTHING TODAY. It is a tripwire, armed for
the moment agents start supplying the field." True when written - 0 of 23 writes
that day carried a `context_key` - and false within hours, which is the point:
it was phrased as a standing property when it was a reading off one afternoon.

The field now arrives. Row 1756 (agent 171, `'DWB-704'`) was written through
this gate and accepted, and is the live verification of the resolvable path.
Row 1755 (agent 203, `'V707-001 / notes'`) carries a well-shaped key but is NOT
attested as having passed here: its author has no `project_id`, so this gate
would refuse it with `context_unscoped_agent`, and it most likely predates the
gate rather than clearing it.

AN OPEN QUESTION IN THE CONCLUDE DESIGN, pointing at no ticket because there is
no ticket. A `working` row carrying a validated `context_key` is inert to
`scan_context`, which raises `not_a_scar` for it - so it can never conclude. If
it is ever retiered to `scar`, it concludes immediately against work that may
have closed long before. Row 1756 is already in exactly that state: its ticket
is closed and the row is `working`. This gate validates keys on every tier
precisely so such a row is not ALSO carrying a key that was never resolvable,
but validation at insert does not answer what should happen on retier.

THE SERVER NEVER INFERS THE SCOPE, and that is a ruling rather than a
convenience. The original proposal was to fill the key from the session's
ticket. `DwbSession` is project-scoped and carries no ticket at all, so the
server would have to guess from the agent's assignments - and of 69 active
agents, 57 have no assigned active ticket and 8 have more than one. Four could
be resolved unambiguously. Manufacturing a scope for the other 94% is the same
move that once read "I could not resolve this" as "this scope is eternal" and
promoted 381 of 455 rows into the tier only a human may grant.

A SCOPE-FREE LESSON IS LEGITIMATE, and the fact that settles it is that
CONCLUSION DELETES THE ROW: `memory_scar_conclude.evict_concluded_scars`
journals the memory and then removes it from `agent_memories`, and the journal
is never auto-loaded. A wrong binding does not mis-file a lesson, it removes it
from recall permanently. `context_key` records WHERE A LESSON WAS LEARNED and
the scan reads it as WHAT THE LESSON APPLIES TO; those are different claims and
conflating them is expensive in one direction only. The worked case: a lesson
about verification written while working on one ticket, bound to that ticket,
is deleted when the ticket closes - hours later - although nothing about it
expired.

So the distinction this module enforces is VALIDITY, not breadth. "The worker on
:8000 serves stale code" stops being true when it restarts and should die with
its context. "A gate you satisfy with your own sentence measures reachability,
not recall" has no closing ticket and must not be made to borrow one.

WHICH IS WHY `context_key` STAYS OPTIONAL AND ABSENCE IS NOT REFUSED. An
author with nothing to bind to writes nothing, exactly as today. What is new is
that an author who has DECIDED the lesson is scope-free can say so, and that
declaration is stored as a judgement rather than being indistinguishable from
the data gap. Keeping those two apart is the whole point: the 381-row incident
happened because one branch could not tell "I looked and found nothing" from "a
human decided this is eternal".

WHAT THIS GATE DELIBERATELY DOES NOT DO. It does not evict anything, and it
does not give a scope-free lesson a death path. The honest death condition for a
lesson that applies everywhere is DISUSE rather than context, and the machinery
exists - but measured recall on this store is currently zero (0 of 12 blind
paraphrases, `fired_count` 0 across the probed corpus), so an eviction keyed on
firing would read every good lesson as unused and delete the corpus. That lane
stays unbuilt behind a recall-health measure. Do not wire it on the strength of
this module existing.
"""

from sqlalchemy.orm import Session

from app.services.memory_scan import (  # noqa: F401 - see module docstring
    _TICKET_CLOSED_STATUSES,
    _resolve_epic,
    _resolve_ticket,
)
from app.models.epic import EpicStatus


class ContextScopeUnresolvable(Exception):
    """Raised when a named scope cannot be resolved, or contradicts itself.

    Its own type rather than a `RawMemoryWriteError` code, for the same reason
    `keyword_reachability.KeywordUnreachable` is its own: the rule belongs to
    every writer of `agent_memories.context_key`, not to the one that got here
    first. The router maps it to 400.
    """

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


# A worked example is part of the message, same ruling as DWB-657's `_GOOD_BODY`
# and DWB-667's `_CONTRAST`. The caller is an agent mid-task holding a value it
# believed was a scope. "context_key must resolve" names a property it cannot
# evaluate; seeing a resolvable one beside an unresolvable one changes the next
# request.
_CONTRAST = (
    "RESOLVABLE, because something can later mark them closed: a ticket key "
    "like 'DWB-704', or an epic name that appears in the text like 'Memory "
    "retrieval'. UNRESOLVABLE, because nothing closes them: 'ABOVE THE FOLD', "
    "'Agreement is not verification', 'API facts that bite' - these are section "
    "headings rather than scopes, which is the shape most of this store's keys "
    "were written in and the reason no scar has ever concluded."
)
# NO COUNT IN THAT SENTENCE, DELIBERATELY. It used to read "424 live rows carry
# exactly this shape", which was true when written and false eight hours later
# when DWB-710 moved 380 of them into another column - in text an agent READS,
# not in a comment. A refusal message is the worst place to put a number that
# moves, because nobody re-reads it the way they re-read a docstring. The
# standing claim survives; the volatile figure is gone.

_SCOPE_FREE_NOTE = (
    "If this lesson is not bound to any one piece of work - a craft lesson that "
    "no ticket closing could ever make untrue - then say so with "
    "`context_free: true` and send no `context_key`. That is a real and common "
    "answer and it is not a worse one. Do NOT reach for a nearby ticket just to "
    "have something to put here: a scar whose context closes is DELETED from "
    "memory and moved to the journal, so borrowing the ticket you happened to be "
    "working on will quietly destroy the lesson when that ticket closes."
)


def require_resolvable_context(
    db: Session,
    *,
    agent,
    context_key: str | None,
    context_free: bool = False,
) -> None:
    """Refuse a scope this project cannot resolve, or a self-contradicting pair.

    THREE REFUSALS, EACH A DIFFERENT CLAIM.

      `context_contradiction` - the write both names a scope and declares
      itself scope-free. Those cannot both be true and the server must not pick
      one; the author knows which they meant.

      `context_unresolvable` - a key was named and resolves to no ticket and no
      epic on this project. The scan would later return `unresolvable`, which
      never concludes, so the binding is decorative: it reads as a scope and
      can never act as one.

      `context_already_closed` - the key resolves to a ticket or epic that is
      ALREADY finished. Nothing is gained by storing it; the row would be
      eligible for conclusion the moment it comes to rest, so the lesson would
      be written and then deleted. Refusing is the only answer that does not
      silently throw the write away.

    ABSENCE IS NOT REFUSED. No key and no declaration passes, exactly as today.
    `context_key` is optional and this gate does not make it mandatory - see the
    module docstring on why an unconditional gate would attach a false scope to
    every genuinely broad lesson.
    """
    key = (context_key or "").strip()

    if key and context_free:
        raise ContextScopeUnresolvable(
            "context_contradiction",
            f"this write names a context ({key!r}) AND declares itself "
            "scope-free with `context_free: true`. Those are opposite claims "
            "and the server will not choose between them. Either this lesson "
            "stops being true when some specific work finishes - send the "
            "context_key and drop the flag - or it does not - send the flag and "
            "drop the key. " + _SCOPE_FREE_NOTE,
        )

    if not key:
        # No scope named. Either a deliberate scope-free declaration or a plain
        # absence; both are allowed and they are stored differently on purpose.
        return

    project_id = getattr(agent, "project_id", None)
    if project_id is None:
        raise ContextScopeUnresolvable(
            "context_unscoped_agent",
            f"agent {getattr(agent, 'id', '?')} belongs to no project, so the "
            f"context {key!r} cannot be resolved against anything. This is a "
            "data problem with the agent rather than with your write.",
        )

    ticket = _resolve_ticket(db, project_id, key)
    if ticket is not None:
        if ticket.status in _TICKET_CLOSED_STATUSES:
            raise ContextScopeUnresolvable(
                "context_already_closed",
                f"context {key!r} resolves to ticket {ticket.ticket_key}, which "
                f"is already {ticket.status.value}. A scar is deleted from "
                "memory and moved to the journal once its context has finished, "
                "so storing this lesson against closed work would write it and "
                "then throw it away at the next scan. Bind it to work that is "
                "still open, or declare it scope-free with `context_free: true` "
                "if no single piece of work owns it.",
            )
        return

    epic = _resolve_epic(db, project_id, key)
    if epic is not None:
        if epic.status == EpicStatus.completed:
            raise ContextScopeUnresolvable(
                "context_already_closed",
                f"context {key!r} resolves to epic {epic.name!r}, which is "
                "already completed. A scar whose context has finished is "
                "deleted from memory and moved to the journal, so this lesson "
                "would be written and then thrown away at the next scan. Bind "
                "it to work that is still open, or declare it scope-free with "
                "`context_free: true`.",
            )
        return

    raise ContextScopeUnresolvable(
        "context_unresolvable",
        f"context {key!r} matches no ticket and no epic on this project, so "
        "nothing can ever mark it finished. A context_key is not a label for "
        "what the lesson is ABOUT - it is the thing whose CLOSING ends this "
        "lesson's life, and the scan resolves it with the same two lookups used "
        f"here: a ticket key found anywhere in the text, or an epic name "
        f"appearing inside it. {_CONTRAST} {_SCOPE_FREE_NOTE}",
    )
