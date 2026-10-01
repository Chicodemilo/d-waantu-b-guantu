# Path: app/schemas/memory_transition.py
# File: memory_transition.py
# Created: 2026-09-30 (DWB-596)
# Purpose: Pydantic response schemas for GET /api/projects/{id}/memory-transition. Every field is DERIVED at read time; there is deliberately no Create or Update model here, because there is no status to write.
# Caller: app/routers/projects.py, app/services/memory_transition.py
# Callees: pydantic, app/models/memory_transition (state vocabularies)
# Data In: values computed by app/services/memory_transition
# Data Out: MemoryTransitionStatusRead, MemoryTransitionAgentRow, TransitionStatus
# Last Modified: 2026-09-30 (DWB-596)

"""Response shapes for the derived transition status.

THERE IS NO Create OR Update MODEL IN THIS FILE AND THAT IS THE TICKET. Miles's
requirement is that the status is programmatic, "not an llm going oh I should
update the display", and the way to hold that is structural rather than by a
rule in prose: a rule is followed until the day it is not, and the failure is
silent, a stale status that still looks live. If an agent CAN write one,
someone eventually will. So there is no status column, no write endpoint and no
request field carrying one, and a test asserts all three.
"""

import enum

from pydantic import BaseModel

from app.models.memory_transition import TransitionDirection, TransitionRunState


class TransitionStatus(str, enum.Enum):
    """What an operator is actually asking when they ask about a transition.

    FIVE VALUES, NOT THREE, and the extra two are the point. An empty result
    must not be the answer to several different questions: a project that never
    transitioned, one that transitioned and finished, one whose entries were
    never enumerated, one part way through and one ready to cut over are five
    different situations, and neither a count of zero nor an absent run can
    tell them apart.

    That is the same requirement as DWB-585's "no candidates" versus "not
    computed", and the same failure if missed: an output that cannot say "I do
    not know" is indistinguishable from one saying "nothing to do".
    """

    not_started = "not_started"
    # Runs exist but none is open. NOT the same as never-started, and keeping
    # them separate is the whole point of this enum: a project that adopted
    # last week and one that has never transitioned both have no open run, and
    # answering both with "not_started" is the empty-result-means-everything
    # failure this ticket exists to prevent. Found by probing a real project
    # whose transition completed instantly, which reported "not_started" about
    # a transition it had just finished.
    idle = "idle"
    # An open run whose entries were never enumerated. Enumeration is atomic
    # with the BEGIN request, so in normal operation this is UNREACHABLE and
    # seeing it means a partial transaction or a hand-edited row. It is
    # reported as its own value rather than folded into in_progress precisely
    # so a consumer can render it as the defect it is instead of as progress.
    not_enumerated = "not_enumerated"
    in_progress = "in_progress"
    # Every entry has reached a terminal state, so the cutover may proceed.
    # This is NOT "the transition is over": the run is still open until the
    # cutover lands.
    complete = "complete"


class MemoryTransitionAgentRow(BaseModel):
    """One agent's share of the run.

    DWB-596 AC4: the breakdown NAMES the agent, so a stalled transition says
    WHO is blocking it rather than only how many rows remain. "14 of 51 done"
    tells an operator to wait; "Freddie has 0 of 12" tells them who to ask.
    """

    agent_id: int
    agent_name: str | None
    entries_total: int
    entries_done: int
    done: bool


class MemoryTransitionStatusRead(BaseModel):
    """The whole status, computed on every request.

    NO COUNT HERE IS STORED. entries_total, entries_done and the per-agent rows
    are aggregated from `memory_transitions` each time this is built. A stored
    count is a second authoritative copy that drifts the moment a row changes
    state without the header being updated, which is the defect this lane has
    now refused three times: the derived score, the seal, and here.
    """

    project_id: int
    status: TransitionStatus

    # Run header fields. All null when there is no open run, which is how
    # "never started" is expressed: not a 404 and not an empty object, so a
    # consumer never needs a try/catch for the normal case.
    run_id: int | None = None
    state: TransitionRunState | None = None
    direction: TransitionDirection | None = None
    started_at: str | None = None
    enumerated_at: str | None = None
    completed_at: str | None = None
    aborted_at: str | None = None

    entries_total: int = 0
    entries_done: int = 0
    # DONE IS NOT THE SAME AS LANDED, and collapsing them is how a display
    # reports success for a transition that moved nothing. All three of
    # `written`, `journaled` and `skipped` are terminal, correctly, because the
    # guard's only question is whether the cutover may proceed. They are not
    # interchangeable to a human deciding whether to confirm one:
    #
    #   written    landed in the new store
    #   journaled  left as an episode; real, but not memory
    #   skipped    deliberately not carried; nothing anywhere
    #
    # A run where every entry was skipped is legitimately complete and has
    # moved nothing, and it should not LOOK like a successful migration.
    # Raised by Barry, who owns the guard, against my first version which
    # reported only entries_done.
    entries_written: int = 0
    entries_journaled: int = 0
    entries_skipped: int = 0
    agents_total: int = 0
    agents_done: int = 0
    agents: list[MemoryTransitionAgentRow] = []
