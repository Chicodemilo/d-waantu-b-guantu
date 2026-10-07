# Path: app/services/memory_score.py
# File: memory_score.py
# Created: 2026-09-29 (DWB-585)
# Purpose: The DERIVED memory score. A pure decay function over
#          (tier, sessions_since_reinforced), the band it falls in, the
#          session-gap query, and the demote / evict / promote candidate lists.
#          The score is NEVER stored, and as of the Miles firing ruling this
#          module writes NOTHING at all - scored_memory() is pure.
# Caller: app/routers/agents.py (GET /api/agents/{id}/memory/scored)
# Callees: app/models/agent_memory, app/models/hook_session,
#          app/models/dwb_session, app/services/journal.promotion_candidates
# Data In: agent_id, a DB session
# Data Out: score(), band(), sessions_since_reinforced(), scored_memory()
# Last Modified: 2026-10-07 (DWB-637 follow-up: UNSCORED_NO_SESSION_ORIGIN's
#                docstring named a write path that no longer exists; the state
#                is still reachable, from two other sources, and now says which.
#                Previous entry: MILES RULING: fired_count's write site moved OUT
#                of this module entirely, to app/services/memory_consult.py.
#                "Deploy doesn't count as a read... outside of normal
#                startup" - scored_memory() is called from spawn/SessionStart
#                injection and DWB-613's dashboard, neither a consultation, so
#                it must never fire anything again. DWB-603's `_fire_scars`
#                and `FIRING_TIERS` are both removed, not disabled - see
#                memory_consult.py for where firing lives now)

"""The consolidation math, done programmatically.

Miles's requirement, and the reason this module exists rather than a prompt:
**the decay, the banding and the candidate lists are a script. The model only
does the SCAN (does this context still apply) and the rewrite.** A prompt that
says "consider demoting things" makes every agent re-derive the rule and
disagree quietly; a function makes it inspectable, testable and identical for
every caller. If the thresholds ever move, they move here, once.

Spec: docs/human_memory_spec.md section 3.

THE SCORE IS DERIVED AND NEVER STORED. There is no `score` column and no `band`
column on `agent_memories`, guarded by tests in two places. A stored score has
to be rewritten on every row every session and drifts out of sync with the rule
it is supposed to express, where a derived score cannot disagree with itself.

THE CLOCK IS SESSIONS, NOT DAYS. Ruled: "a day is an interval bw sleep". Decay
tracks EXPERIENCE. An agent that has not worked for three weeks has forgotten
nothing, because nothing happened to it.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.dwb_session import DwbSession
from app.models.hook_session import HookSession
from app.models.project import MemoryMode, Project
from app.services import journal as journal_svc

# ---------------------------------------------------------------------------
# The section 3 table.
# ---------------------------------------------------------------------------
# Columns, in order: this session | 1-5 | 6-14 | 15-30 | 31-90 | 90+
#
# Transcribed from the spec rather than derived from a formula, deliberately.
# The curve is not a clean exponential and the spec calls the parameters
# "tunable against real data rather than argued about", so a table that can be
# edited to match a ruling beats a formula that has to be re-fitted to one.
_CURVE: dict[MemoryTier, tuple[int, ...]] = {
    MemoryTier.core: (10, 10, 10, 10, 10, 10),
    # DWB-611: scar_context_bound collapsed into scar - it carried the
    # identical tuple here even before the collapse, so removing the second
    # key changes nothing this function returns.
    MemoryTier.scar: (10, 9, 8, 7, 6, 6),
    MemoryTier.working: (10, 8, 6, 4, 2, 1),
}

# Upper bound of each bucket; the last bucket is open-ended.
#
# 90 appears in BOTH "31-90" and "90+" in the spec table. Read here as: 90 is
# the last session of the 31-90 bucket and 91 is the first of 90+, so each
# bucket is a closed range and no session count falls in two. It only changes
# an answer for WORKING (2 versus 1), and it is written down because a reader
# checking the table against this code will otherwise have to guess.
_BUCKET_UPPER = (0, 5, 14, 30, 90)

# THE TWO FLOORS THAT ARE NOT FUNCTIONS OF SESSIONS. Per the spec amendment:
# "The arithmetic floors at 1. Zero is not a computed score, it is an eviction
# state." WORKING bottoms at 1 and context-bound scars bottom at 6 by decay,
# reaching 0 only by STEP when the SCAN finds the context dead. So this module
# NEVER returns 0. Implementing the decay down to 0 instead is the single
# easiest way to get this ticket wrong, and it would pass tests written from
# the same misreading.
MIN_DERIVED_SCORE = 1

# Bands, spec section 3 "What the score does".
BAND_FULL_TEXT = "full_text"  # 8-10: carried in full
BAND_COMPRESSED = "compressed"  # 5-7: carried, one line
BAND_DEMOTION_CANDIDATE = "demotion_candidate"  # 2-4: flagged next consolidation
BAND_LAST_CONSOLIDATION = "last_consolidation"  # 1: last pass before it goes

# Why a memory has no score. Named rather than left as a bare null, for the
# reason node_retrieval and journal both name their states: an empty or null
# field cannot distinguish "nothing applied" from "nothing ran".
UNSCORED_UNTIERED = "untiered"
"""tier is `raw`. The row has been appended but consolidation has not judged
it. Spec section 4 forbids tiering in the moment, so this is the normal state
of a fresh row, not a defect. Excluded from scoring until it is tiered."""

UNSCORED_NO_SESSION_ORIGIN = "no_session_origin"
"""Both last_reinforced_session_id and created_session_id are NULL, so the row
has no point on the clock to count from.

STILL REACHABLE, BUT NO LONGER BY A WRITE (DWB-637). This used to read
"Reachable: DWB-586 accepts a write when no DWB session is open and records
created_session_id as NULL". That path is gone - every writer of
`agent_memories` resolves its origin through
`memory_origin.require_session_origin`, which refuses rather than stamping NULL.
The constant still earns its place, because two sources remain:

  - Rows written before that guard landed.
  - `project.delete_project`, which NULLs `created_session_id` on memories whose
    originating session is being deleted (project.py ~721) instead of deleting
    the rows, because agents are global and must not lose lessons when an
    unrelated project goes. That path INTENDS the NULL, which is why a NOT NULL
    constraint on the column is a design question rather than a cleanup.

This is deliberately NOT treated as "zero sessions elapsed", which would score
it 10 forever, nor as "infinitely old", which would evict it. Both are guesses
dressed as arithmetic. The honest answer is that the clock has no origin for
this row, so it is reported unscored and kept out of every candidate list."""


def score(tier: MemoryTier, sessions_since_reinforced: int) -> int:
    """The decay curve. Pure: no database, no clock, no I/O.

    Raises ValueError for `raw`, which has no curve because it has no tier yet;
    callers must check. That is louder than returning a default, and DWB-584
    made `raw` a named enum value precisely so this call site has to handle it
    rather than skipping those rows silently.
    """
    if tier == MemoryTier.raw:
        raise ValueError(
            "raw memories are untiered and have no score until consolidation "
            "tiers them (spec section 4)"
        )
    if sessions_since_reinforced < 0:
        raise ValueError("sessions_since_reinforced cannot be negative")

    curve = _CURVE[tier]
    for index, upper in enumerate(_BUCKET_UPPER):
        if sessions_since_reinforced <= upper:
            return curve[index]
    return curve[-1]


def band(value: int) -> str:
    """Which treatment a score earns (spec section 3).

    Without this the number is decoration; with it, consolidation is sorting
    rather than judgement.
    """
    if value >= 8:
        return BAND_FULL_TEXT
    if value >= 5:
        return BAND_COMPRESSED
    if value >= 2:
        return BAND_DEMOTION_CANDIDATE
    return BAND_LAST_CONSOLIDATION


def sessions_since_reinforced(db: Session, memory: AgentMemory) -> int | None:
    """How many CLOSED DWB sessions this agent has had since the memory's clock
    origin. Returns None when the row has no origin (see
    UNSCORED_NO_SESSION_ORIGIN).

    THE COALESCE IS LOAD-BEARING AND IS AN ACCEPTANCE CRITERION, NOT A STYLE
    CHOICE. `last_reinforced_session_id` is NULL on a never-reinforced row,
    which is MOST rows, and `id > NULL` is UNKNOWN in SQL rather than true, so
    the comparison matches nothing and the count comes back 0. Zero sessions
    since reinforcement means a score of 10, forever, on exactly the memories
    that have never fired once. It is silent, it is wrong in the flattering
    direction, and a unit test whose fixture memory is also never-reinforced
    agrees with it. Hence COALESCE(last_reinforced, created).

    HOOK SESSIONS WITH NO DWB SESSION ARE SKIPPED, AND THAT IS INTENDED
    (DWB-584). `hook_sessions.dwb_session_id` is nullable because historical
    rows predate the DWB session model. A hook session never linked to a DWB
    session is not an experience that should tick the decay clock, so dropping
    those is the right behaviour, not an accident. Do not "fix" it.

    Two things drop them here and it is worth naming both, because removing
    either one alone would not change the result and could read as dead code:
    the INNER JOIN to dwb_sessions cannot match a NULL, and COUNT(DISTINCT ...)
    would skip NULLs anyway. The join is doing the work; the count is
    belt-and-braces and also what makes repeated hook sessions inside one DWB
    session count as one experience rather than several.

    Only CLOSED sessions count. An open session is the one currently happening;
    it becomes experience when it ends, which is what makes the tick a session
    open/close rather than a wall-clock event.
    """
    origin = memory.last_reinforced_session_id
    if origin is None:
        origin = memory.created_session_id
    if origin is None:
        return None

    return db.execute(
        select(func.count(func.distinct(HookSession.dwb_session_id)))
        .select_from(HookSession)
        .join(DwbSession, DwbSession.id == HookSession.dwb_session_id)
        .where(
            HookSession.agent_id == memory.agent_id,
            DwbSession.closed_at.is_not(None),
            DwbSession.id > origin,
        )
    ).scalar_one()


def _entry(db: Session, memory: AgentMemory) -> dict:
    """One row's scored shape, including the reason when it has no score.

    DWB-610: carries `body` (added to this shape rather than opening a second
    read path). Context assembly needs the full 8-10 band as full text, and
    the only other way to get there is a second query keyed on the same ids
    this endpoint already computed - two paths reading the same rows is
    exactly the disagreement risk section 7 opens with. `body` is raw memory
    content, not a derived fact, so it does not touch either guard: no
    `score`/`band` column exists on the model and none is added here.
    """
    base = {
        "id": memory.id,
        "tier": memory.tier.value,
        "body": memory.body,
        "context_key": memory.context_key,
        "fired_count": memory.fired_count,
    }

    if memory.tier == MemoryTier.raw:
        return {
            **base,
            "scored": False,
            "reason": UNSCORED_UNTIERED,
            "sessions_since_reinforced": None,
            "score": None,
            "band": None,
        }

    gap = sessions_since_reinforced(db, memory)
    if gap is None:
        return {
            **base,
            "scored": False,
            "reason": UNSCORED_NO_SESSION_ORIGIN,
            "sessions_since_reinforced": None,
            "score": None,
            "band": None,
        }

    value = score(memory.tier, gap)
    return {
        **base,
        "scored": True,
        "reason": None,
        "sessions_since_reinforced": gap,
        "score": value,
        "band": band(value),
    }


class MemoryScoreError(Exception):
    """Raised for conditions the router turns into a 4xx."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


# Why a scoring run produced nothing, as a VALUE rather than as an empty list.
# Acceptance 5: "no candidates" and "not computed" must be distinguishable, and
# an empty list means both.
NOT_COMPUTED_STOCK_MODE = "project_not_in_human_memory_mode"
NOT_COMPUTED_AGENT_UNSCOPED = "agent_has_no_project"


def scored_memory(db: Session, *, agent_id: int) -> dict:
    """Every memory for an agent with its derived score, plus the three lists.

    THE LISTS ARE PRODUCED HERE, BY CODE. That is the whole point of the
    ticket: a playbook paragraph telling an agent to "consider demoting things"
    is the version this replaces.

    The three are not symmetric, and it matters:

    - `demote`  memories in band 2-4, flagged for the next consolidation.
    - `evict`   memories at 1, the last consolidation before they go. Eviction
                itself is an ACT, not an arithmetic result, and per section 7
                hard rule 4 whatever leaves memory is written to the journal
                first. This list nominates; it does not remove - DWB-607's
                `memory_evict.evict_working_memories` is the ACT, and it
                recomputes the same band directly off `score()`/`band()`
                rather than calling this function, built independently of
                this function's firing question before Miles ever ruled on
                it (this function fires nothing now regardless).
    - `promote` JOURNAL entries reached for at least PROMOTION_THRESHOLD times,
                which section 5 says are overdue to stop being a story. It
                delegates to journal.promotion_candidates rather than
                re-implementing the threshold, because two copies of a number
                the spec ruled once is how they end up disagreeing.

    Note what `promote` is NOT, STILL, even after DWB-606: the scar-to-CORE
    promotion of section 2. That one now DOES run automatically
    (`memory_promote.maybe_promote_scar`, triggered by fired_count reaching 3
    or the context-liveness scan reporting `cannot_die`), but it is not a
    NOMINATION list the way `demote`/`evict`/`promote` are - it acts inline on
    one scar at a time rather than surfacing candidates for something else to
    consume, so it has no id list to belong in here. This docstring said CORE
    was "never touched by automatic consolidation" before DWB-606; that
    claim was true when written and is false now, which is exactly why a
    docstring naming a mechanism by what it is NOT has to be re-read the
    moment that mechanism ships, not left standing on the assumption that
    still describes the code. Section 7 hard rule 5's ADOPT-time restriction
    (memory_decide.py's DECIDABLE_TIERS excluding core) is untouched: this is
    Miles's own carved-out recurrence-driven exception to it, not a breach.
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise MemoryScoreError("agent_not_found", f"agent {agent_id} not found")

    empty = {
        "agent_id": agent_id,
        "entries": [],
        "demote": [],
        "evict": [],
        "promote": [],
    }

    if agent.project_id is None:
        return {
            **empty,
            "computed": False,
            "reason": NOT_COMPUTED_AGENT_UNSCOPED,
            "memory_mode": None,
        }

    project = db.get(Project, agent.project_id)
    mode = project.memory_mode if project is not None else None
    if mode != MemoryMode.human_memory:
        # Not an error. Scoring is meaningless in stock mode, and saying so is
        # more useful than returning three empty lists that read as "nothing to
        # do". Section 7 hard rule 1: when human_memory is on it is the ONLY
        # memory, and when it is off this schema is simply not in play.
        return {
            **empty,
            "computed": False,
            "reason": NOT_COMPUTED_STOCK_MODE,
            "memory_mode": mode.value if mode is not None else None,
        }

    memories = list(
        db.execute(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent_id)
            .order_by(AgentMemory.id.asc())
        )
        .scalars()
        .all()
    )

    # MILES RULING: nothing fires here, ever. This is a LIST, not a
    # consultation - it can be satisfied with no question in it ("give me
    # everything"), which is exactly what makes a read injection-shaped
    # rather than a deliberate "have I made this error before". See
    # memory_consult.py for where firing actually happens now.
    entries = [_entry(db, memory) for memory in memories]

    return {
        "agent_id": agent_id,
        "computed": True,
        "reason": None,
        "memory_mode": mode.value,
        "entries": entries,
        "demote": [e["id"] for e in entries if e["band"] == BAND_DEMOTION_CANDIDATE],
        "evict": [e["id"] for e in entries if e["band"] == BAND_LAST_CONSOLIDATION],
        "promote": [
            j.id for j in journal_svc.promotion_candidates(db, agent_id=agent_id)
        ],
    }
