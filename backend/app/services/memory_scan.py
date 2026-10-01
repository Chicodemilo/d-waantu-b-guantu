# Path: app/services/memory_scan.py
# File: memory_scan.py
# Created: 2026-09-30 (DWB-604)
# Purpose: The context-liveness SCAN for scar-family memories - given a scar,
#          answer whether the context it was filed under is still active, has
#          concluded, or was never tied to anything that could conclude at
#          all. Two distinct output signals, no execution here.
# Caller: DWB-606 (scar-to-core promotion) and DWB-607 (scar-to-journal on a
#         finished context) will call this; this ticket only answers the
#         question
# Callees: app/models/agent, app/models/agent_memory, app/models/epic,
#          app/models/ticket, app/models/project
# Data In: db Session, an AgentMemory (scar family)
# Data Out: ContextLiveness
# Last Modified: 2026-09-30 (DWB-611: scar_context_bound collapsed into scar -
#                SCAR_FAMILY is now a single-element tuple; the module's own
#                logic never branched on the removed tier value)

"""The SCAN, named in five comments before this ticket and built nowhere.

FROM THE HUMAN MEMORY AUDIT, 2026-09-30: `agent_memory.py:70`,
`routers/agents.py:568`, `journal.py:104`, `memory_score.py:19` and `:74`, and
`memory_decide.py:246` all say "the SCAN" and none of them is it.

Miles's rule needs two distinct movements out of this one question:

1. A scar at 6 whose context has FINISHED moves into the JOURNAL (worked
   example: scars accumulated while working on documents for the
   IndependenceDay project; that work is done, so the context is gone).
2. A scar whose context is so broad it structurally CANNOT die is a durable
   lesson and becomes CORE.

THE THIRD ANSWER THAT MUST EXIST FOR THE OTHER TWO TO MEAN ANYTHING: a scar
whose context is a real, identifiable, STILL-OPEN thing gets neither signal.
Without a genuine "still alive, do nothing" outcome, "not finished" and
"cannot die" collapse into the same case by elimination, which is exactly the
guard shape this project keeps getting bitten by: a check whose two real
answers differ only by fiat. `ContextLiveness.still_active` is that third
answer, and every test file that touches this module should have to prove it
separately from the other two, not infer it as "whatever this isn't".

THE CONTRACT: `context_key` is a free-text heading path (set when a scar was
filed with a heading and it survived the adopt - see memory_decide.py's
`_body_of`; DWB-611 removed the second tier value this used to be gated on,
so it is now just "did the row have a heading", not "which tier was chosen"),
not a foreign key. There is no column that
points at an epic or a ticket. So resolving it is a LOOKUP, not a join, and
the lookup can fail to find anything at all - that failure IS the "cannot
die" signal, not an error state, because a context that names nothing the
system can track is, definitionally, a context with no lifecycle event that
could ever mark it closed.

RESOLUTION ORDER, TICKET BEFORE EPIC: `context_key` may embed a specific
ticket key (e.g. "DWB-590 / some heading"), which is the more precise unit
when present, before falling back to matching an epic's name as the broader
"project area" the ticket describes. Sprint is deliberately NOT matched here:
Miles's worked example and this ticket's own acceptance text both speak at
ticket/epic grain, and adding a third lookup for marginal gain is exactly the
kind of scope creep that turns one ticket's design into two tickets' worth of
matching heuristics nobody asked to review. If sprint-grain context turns up
in practice, it is a follow-up, not a silent addition here.

ON AN UNRESOLVABLE PROJECT (the agent has none, or it is missing): reported
`still_active`, not `cannot_die`. These are different failures with different
costs. `cannot_die` is a POSITIVE claim ("nothing here could ever close"),
and DWB-606 acts on it by writing `tier=core` - a promotion that, per section
7 hard rule 5, is supposed to be rare and durable. Manufacturing that claim
from "I could not even look" would promote on missing data. `still_active` is
the side that does nothing, so an unresolvable project just waits for the
next scan rather than wrongly promoting or wrongly journaling.
"""

import enum
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.epic import Epic, EpicStatus
from app.models.ticket import Ticket, TicketStatus

# The tier this scan is defined over. DWB-611 collapsed scar_context_bound
# into scar - a `scar` row carries a context_key when memory_decide.py had a
# heading path to give it and None otherwise, which this module treats as the
# "no context named at all" case rather than as an error - see
# `scan_context`'s first branch. Left as a tuple (one element, not a lone
# MemoryTier) so callers iterating SCAR_FAMILY need no special case for the
# single-tier shape - same reasoning as memory_score.FIRING_TIERS.
SCAR_FAMILY: tuple[MemoryTier, ...] = (MemoryTier.scar,)

# A ticket is done with its work whether it shipped or was dropped; either
# way nothing further will happen under that key.
_TICKET_CLOSED_STATUSES = frozenset({TicketStatus.done, TicketStatus.cancelled})

# Matches a ticket key anywhere inside a free-text context_key, e.g. picks
# "DWB-590" out of "DWB-590 / Migrations". Anchored to word boundaries so it
# does not match a fragment inside a longer token.
_TICKET_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*-\d+)\b")


class ContextLiveness(str, enum.Enum):
    """The three answers the SCAN can give. Exactly three, not two: see the
    module docstring on why `still_active` has to be a real outcome rather
    than the leftover space between the other two."""

    still_active = "still_active"  # a real, identifiable, still-open context
    finished = "finished"  # resolved to a closed ticket or a completed epic
    cannot_die = "cannot_die"  # a named context that resolves to nothing trackable


class ScanError(Exception):
    """Raised for a memory the scan is not defined over."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _resolve_ticket(db: Session, project_id: int, context_key: str) -> Ticket | None:
    match = _TICKET_KEY_RE.search(context_key)
    if match is None:
        return None
    key = match.group(1)
    return db.scalar(
        select(Ticket).where(
            Ticket.project_id == project_id,
            func.upper(Ticket.ticket_key) == key.upper(),
        )
    )


def _resolve_epic(db: Session, project_id: int, context_key: str) -> Epic | None:
    """Case-insensitive containment: does the epic's name appear inside the
    heading path? Not the reverse - matching the heading path inside a short
    epic name would let a generic epic title ("Backend") swallow almost any
    heading that happens to contain the word, which is the false-"finished"
    direction this scan cannot afford (see the module docstring on why a
    positive claim here has to earn it)."""
    epics = db.execute(
        select(Epic).where(Epic.project_id == project_id)
    ).scalars().all()
    lowered = context_key.lower()
    for epic in epics:
        if epic.name and epic.name.strip().lower() in lowered:
            return epic
    return None


def scan_context(db: Session, memory: AgentMemory) -> ContextLiveness:
    """Answer, for one scar-family memory, whether its context is still
    alive, has concluded, or was never tied to anything that could conclude.

    COUNTER WRITE ONLY... no, this one is READ ONLY: unlike DWB-603's
    `_fire_scars`, nothing here writes to the database. It answers a
    question; DWB-606 and DWB-607 are what act on the answer.

    Raises ScanError for a tier this scan is not defined over. `raw` has no
    context to have concluded; WORKING moves by decay-floor eviction, not by
    a context-liveness question; CORE is never touched by automatic
    consolidation at all (section 7 hard rule 5). Calling this on any of them
    is a caller error, not a state this function should paper over with a
    guessed answer.
    """
    if memory.tier not in SCAR_FAMILY:
        raise ScanError(
            "not_a_scar",
            f"the context scan is only defined for scar-family memories "
            f"({', '.join(t.value for t in SCAR_FAMILY)}); memory {memory.id} "
            f"is tier {memory.tier.value}",
        )

    if not memory.context_key or not memory.context_key.strip():
        # DWB-604/611 SEQUENCING RULING (Archie + Stan + Barry, 2026-09-30):
        # this branch changes meaning the moment DWB-611 lands, and it has
        # now landed. BEFORE the collapse, a plain `scar` never carried a
        # context_key by construction (memory_decide.py set one only for
        # `scar_context_bound`), so "no key" reliably meant "an agent
        # deliberately judged this context-independent" - Miles's own
        # "general coding-standards lesson" case, and `cannot_die` was right.
        #
        # AFTER the collapse, Miles's ruling is that ALL scars are context
        # bound - there is no longer a tier value that means "deliberately
        # has no context". So a missing context_key can no longer mean
        # "deliberately general"; it can only mean the context was never
        # RECORDED, which is a data gap, not a judgement. That is the SAME
        # failure as an unresolvable project two branches below: "could not
        # look", not "will never close" - so it gets the same answer,
        # `still_active`, and takes no action rather than promoting on
        # missing data.
        #
        # NOTHING IS LOST BY THIS CHANGE. The genuine broad-context case
        # (coding standards, etc.) survives entirely through the
        # named-but-unresolvable branch at the bottom of this function, which
        # the collapse does not touch: an EXPLICIT context_key that names
        # nothing this project can track still reports `cannot_die`. This
        # branch was only ever doing double duty as a stand-in for that case
        # when a scar had no key recorded at all; after DWB-611 that duty
        # moves entirely to the branch that already does it correctly.
        return ContextLiveness.still_active

    agent = db.get(Agent, memory.agent_id)
    if agent is None or agent.project_id is None:
        # Cannot even look. See the module docstring: this is NOT the same
        # claim as `cannot_die`, which asserts the context will never close.
        # Here we simply have no project to search in, so we default to the
        # side that takes no action.
        return ContextLiveness.still_active

    ticket = _resolve_ticket(db, agent.project_id, memory.context_key)
    if ticket is not None:
        return (
            ContextLiveness.finished
            if ticket.status in _TICKET_CLOSED_STATUSES
            else ContextLiveness.still_active
        )

    epic = _resolve_epic(db, agent.project_id, memory.context_key)
    if epic is not None:
        return (
            ContextLiveness.finished
            if epic.status == EpicStatus.completed
            else ContextLiveness.still_active
        )

    # A context was named, but it resolves to nothing this project can
    # track: no ticket key found in it, no epic name contained in it. That is
    # not a lookup failure to apologise for - it is the definition of a
    # context broad enough that nothing in the system could ever mark it
    # closed, which is exactly Miles's "so broad it can never go away".
    return ContextLiveness.cannot_die
