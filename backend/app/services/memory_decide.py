# Path: app/services/memory_decide.py
# File: memory_decide.py
# Created: 2026-09-30 (DWB-594)
# Purpose: The DECIDE phase - hand an agent ONE candidate and one question,
#          record the answer, write or journal-then-skip, and let the cutover
#          fire when the last row lands. The phase the whole lane protects.
# Caller: DWB-594's decide endpoint
# Callees: app/services/memory_cutover, app/models/agent_memory,
#          app/models/journal_entry, app/models/memory_transition
# Data In: db Session, agent_id, transition id, a tier
# Data Out: the updated MemoryTransition; the mode landed in, if it cut over
# Last Modified: 2026-10-01 (DWB-634: _decision_now delegates to the shared
#                app.services.timestamps helper, same expression, one owner;
#                previous entry: DWB-633 decided_at is truncated to the second
#                at source - MySQL rounds a microsecond value HALF-UP into a
#                DATETIME(0), storing decisions in the future)
#                parity with raw_memory.py - its absence made every adopted row
#                unscoreable and therefore unreachable)

"""One entry, one question. The phase a shortcut would destroy.

DWB-594 phase 2, verbatim: "The agent is handed ONE entry and ONE question:
which tier. Not the file." Miles: "I don't want to leave it to just a giant
context list."

THE INTERFACE CANNOT HAND OVER THE WHOLE FILE, and that is enforced rather than
documented: `next_entry` returns one row or None, and there is no function here
that returns a collection of candidates. A test asserts that over the module's
public surface, because a `list_entries` helper added later for convenience is
exactly how this constraint would be lost - it would look like an improvement.

ON UNCERTAINTY, TIER DOWN. The ticket's own words, and the reason this phase can
be trusted to an agent at all: the errors are not symmetric. A wrongly-CORE
entry never fades and loads every session forever; a wrongly-WORKING one fades,
gets journaled and is recoverable. Every available mistake is recoverable except
tiering too high, and that one is forbidden outright below.

CORE IS NOT A DECISION AVAILABLE HERE. Spec section 7 hard rule 5: CORE is never
touched by automatic consolidation - only a human retires a ruled entry, and only
logged cross-context evidence adds a graduated one. An agent adopting its own
back catalogue is neither. The ticket says so directly: "An agent unsure between
SCAR and CORE picks SCAR, and the recurrence mechanism promotes it later on
evidence, which is the spec's own promotion path doing its job rather than a
workaround for a bad guess." Same refusal DWB-586 makes on the raw write, for
the same rule.

JOURNAL BEFORE SKIP, IN THAT ORDER (TL ruling, 2026-09-30). A skipped candidate
looks recoverable, because sealing the flat file destroys nothing and a revert
unseals it. It is not: DWB-595's revert RENDERS THE STORE OVER THE FILE, and a
skipped entry has no row in the store, so the revert overwrites the intact
original with a version excluding exactly the content it was supposed to
recover. The recovery path is the deletion. So every skip is journaled first -
noise and judgement alike, because the state cannot tell them apart and the
journal is append-only, never auto-loaded and free until reached for, so a
duplicate sitting in it costs essentially nothing.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_memory import AgentMemory, MemoryTier
from app.models.journal_entry import JournalEntry
from app.models.memory_transition import (
    TERMINAL_STATES,
    MemoryTransition,
    MemoryTransitionRun,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project
from app.services import dwb_session as session_svc
from app.services import memory_format
from app.services import timestamps

# Tiers an adopting agent may choose. `core` and `raw` are both absent, for
# different reasons, and both absences are load-bearing:
#   core - hard rule 5; reachable only by a human ruling or logged evidence
#   raw  - the absence of a judgement, which is what this phase exists to supply
#
# DWB-611: `scar_context_bound` is gone as a SEPARATE choice - Miles's ruling
# is four buckets, all scars context-bound, not two tier values an agent picks
# between. There is only one scar decision now; whether context_key gets set
# depends on whether a heading path is available, not on which of two values
# was chosen (see _body_of's caller below).
DECIDABLE_TIERS: frozenset[MemoryTier] = frozenset(
    {MemoryTier.scar, MemoryTier.working}
)

# Tags every journal entry written by a skip carries, so the reason an episode
# is in the journal is legible later without joining back to a transition row
# that may since have been aborted away.
SKIP_TAGS = ["adopt", "skipped"]


class DecideError(Exception):
    """Raised by this module; the router maps `code` to a status."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def _open_run(db: Session, project_id: int) -> MemoryTransitionRun | None:
    return db.scalar(
        select(MemoryTransitionRun)
        .where(MemoryTransitionRun.project_id == project_id)
        .where(MemoryTransitionRun.state == TransitionRunState.open)
    )


def next_entry(db: Session, *, agent_id: int) -> MemoryTransition | None:
    """The ONE candidate this agent should answer next, or None when done.

    Returns a single row, never a collection, and that is the constraint the
    whole lane exists to protect rather than an implementation detail. There is
    deliberately no `remaining()` or `list_entries()` beside it: a convenience
    helper returning all of them would look like an improvement and would hand
    back the giant context list this design rules out.

    Oldest first, so the order an agent answers in matches the order the entries
    were written, which is the order they make sense in.
    """
    agent = db.get(Agent, agent_id)
    if agent is None or agent.project_id is None:
        return None
    run = _open_run(db, agent.project_id)
    if run is None:
        return None
    return db.scalar(
        select(MemoryTransition)
        .where(MemoryTransition.run_id == run.id)
        .where(MemoryTransition.agent_id == agent_id)
        .where(MemoryTransition.state.notin_(list(TERMINAL_STATES)))
        .order_by(MemoryTransition.id.asc())
        .limit(1)
    )


def remaining_count(db: Session, *, agent_id: int) -> int:
    """How many are left. A COUNT, never the entries themselves.

    Exists so a caller can show progress without being handed the queue. The
    distinction is the point: a number cannot be pasted into a prompt, and this
    is the shape that stays safe when someone wants "how much is left".
    """
    agent = db.get(Agent, agent_id)
    if agent is None or agent.project_id is None:
        return 0
    run = _open_run(db, agent.project_id)
    if run is None:
        return 0
    return len(
        db.execute(
            select(MemoryTransition.id)
            .where(MemoryTransition.run_id == run.id)
            .where(MemoryTransition.agent_id == agent_id)
            .where(MemoryTransition.state.notin_(list(TERMINAL_STATES)))
        )
        .scalars()
        .all()
    )


def _load(db: Session, transition_id: int) -> MemoryTransition:
    row = db.get(MemoryTransition, transition_id)
    if row is None:
        raise DecideError("not_found", f"transition {transition_id} not found")
    if row.state in TERMINAL_STATES:
        raise DecideError(
            "already_decided",
            f"transition {transition_id} is already {row.state.value}. Deciding "
            "it twice would either duplicate a memory row or overwrite a "
            "recorded judgement; neither is recoverable from the row itself.",
        )
    return row


def _decision_now() -> datetime:
    """Now, TRUNCATED to the second, because the column cannot hold more.

    DWB-633. `decided_at` is a `DateTime` with no fractional seconds. MySQL
    does not truncate a value carrying a fraction on the way in, it ROUNDS IT
    HALF-UP, so a decision made at :24.635 is stored as :25 - recorded half a
    second after it happened, in the future relative to the event.

    THE PROBLEM IS THE FRACTION, NOT THE WRITER, and getting that backwards
    points at a fix that does not work. It is tempting to read this as "Python
    stamps round, MySQL stamps truncate" and therefore to tidy this helper away
    into a server-side default. That reintroduces the bug: measured,
    `CAST(NOW(3) AS DATETIME)` at .513/.629/.749/.865 all round UP, while plain
    `NOW()` at the same instants does not. `NOW()` is safe because it is
    GENERATED at second precision and has no fraction to round, not because
    MySQL produced it. Anything carrying a fraction is rounded, wherever it
    came from.

    So the fix is to remove the fraction, which is what this does, and a
    server-side expression is an acceptable substitute ONLY if it generates at
    second precision.

    The asymmetry that made it visible: `created_at` on this table is plain
    `NOW()`, so it has no fraction while `decided_at` had one. Comparing them
    therefore carried an error of up to a FULL second in an unpredictable
    direction. Measured: a decision stored at :25 sitting "after" a row
    genuinely created at :24.6 and stored at :24.

    Anything ordering these two columns inherits that, which is how it surfaced
    - as intermittent failures in the DWB-623 recession detector, where a late
    arrival could look earlier than the decision it followed. Truncating here
    makes both sides agree, at the source, rather than compensating downstream
    with a tolerance that would blunt the comparison for every caller.

    Truncation rather than rounding because a timestamp should never name a
    moment that has not happened yet.
    """
    return timestamps.aware_utc_now_second()


def _body_of(row: MemoryTransition) -> tuple[str, tuple[str, ...]]:
    """The lesson and its heading chain, recovered from the stored excerpt.

    `source_excerpt` holds `memory_format.render([entry])` rather than a raw
    slice, so the chain travels in the column that already exists. Recovering it
    through `split` is the other half of that trade, and the format module's
    round-trip identity is what makes it exact.
    """
    parsed = memory_format.split(row.source_excerpt or "")
    if not parsed.entries:
        # The excerpt did not round-trip. Not silently recoverable: writing the
        # raw excerpt as a memory body would smuggle heading markup into a
        # lesson, and dropping it would lose the entry.
        raise DecideError(
            "excerpt_unreadable",
            f"transition {row.id}'s source_excerpt did not split back into an "
            "entry. The adopt path stores excerpts as rendered entries and "
            "relies on render/split being exact inverses; this one is not, so "
            "the entry cannot be written without guessing at its content.",
        )
    entry = parsed.entries[0]
    return entry.body, entry.heading_path


def decide(
    db: Session,
    *,
    transition_id: int,
    tier: str,
    decided_by: str,
    reason: str | None = None,
) -> MemoryTransition:
    """Record a tier for ONE candidate and write it into the store.

    `reason` IS PERSISTED, and this parameter not existing is what made a whole
    migration's reasoning disappear. The router and
    `decide_and_maybe_cut_over` both carried the field; this signature did not
    accept it, so the tiering branch silently discarded what the skip branch
    kept. The failure was invisible from outside: a 200 came back either way.
    Keep it a stored column rather than a passed-through log line - an agent
    judging one entry at a time uses the reason to flag the rows a human must
    revisit, and that flag is the lane's only channel to a person.

    Refuses `core` (hard rule 5) and `raw` (the absence of a judgement). The
    refusal names the rule, and for `core` it names the alternative, because
    "pick SCAR and let recurrence promote it" is the actual next action and a
    refusal that withholds it just gets worked around.

    Does not commit. The caller owns the transaction, so the memory row, the
    state change and any cutover it triggers land together or not at all.
    """
    row = _load(db, transition_id)

    try:
        chosen = MemoryTier(tier)
    except ValueError:
        raise DecideError(
            "unknown_tier",
            f"'{tier}' is not a tier. Choose one of: "
            + ", ".join(sorted(t.value for t in DECIDABLE_TIERS)),
        )

    if chosen == MemoryTier.core:
        raise DecideError(
            "core_forbidden",
            "CORE cannot be chosen while adopting. Spec section 7 hard rule 5: "
            "only a human retires a ruled entry, and only logged cross-context "
            "evidence adds a graduated one; an agent adopting its own back "
            "catalogue is neither. Choose SCAR instead - on uncertainty, tier "
            "down - and the recurrence mechanism promotes it later on evidence.",
        )
    if chosen not in DECIDABLE_TIERS:
        raise DecideError(
            "tier_not_decidable",
            f"'{tier}' is not a decision. Spec section 4 makes `raw` the state a "
            "row is written in BEFORE a judgement; choosing it here would record "
            "the absence of the judgement this phase exists to supply.",
        )

    body, heading_path = _body_of(row)

    # DWB-620: STAMP THE SESSION ORIGIN, AT PARITY WITH raw_memory.py.
    #
    # This line's absence was the outage. Every adopted row was written with a
    # NULL origin, `memory_score.sessions_since_reinforced` returns None for a
    # row with neither `last_reinforced_session_id` nor `created_session_id`,
    # and a row that cannot be scored is excluded from every candidate list and
    # never rendered. 396 rows adopted; spawn-prepare returned instructions and
    # no memory; the flat file was sealed behind the mode, so there was no
    # fallback. An omission on ONE writer, not a missing capability.
    #
    # NULL when no session is open is the RAW PATH'S OWN RULE and is kept
    # deliberately rather than improved on here: losing the lesson because the
    # bookkeeping was not ready is the worse outcome, and inventing a different
    # rule for adoption is how the two writers drift apart again.
    active = session_svc.get_active_session(db, row.project_id)

    memory = AgentMemory(
        agent_id=row.agent_id,
        tier=chosen,
        body=body,
        created_session_id=active.id if active is not None else None,
        # DWB-611: every scar is context-bound now, so context_key is set for
        # every `scar` row a heading path is available for, not a subset
        # gated by a second tier value. A row with no heading (or any other
        # tier) still gets None: the column means nothing outside `scar`, and
        # a value there would read as a binding the SCAN should test.
        context_key=(
            " / ".join(heading_path)
            if chosen == MemoryTier.scar and heading_path
            else None
        ),
    )
    db.add(memory)
    db.flush()

    row.decided_tier = chosen
    row.decided_by = decided_by
    row.reason = reason
    row.decided_at = _decision_now()
    row.target_memory_id = memory.id
    row.state = TransitionState.written
    db.flush()
    return row


def skip(
    db: Session, *, transition_id: int, decided_by: str, reason: str | None = None
) -> MemoryTransition:
    """Decline to carry a candidate forward - JOURNALING IT FIRST.

    THE ORDER IS THE POINT AND IT IS TESTABLE. Spec section 7 hard rule 4:
    journal, then rewrite; losing it in flight is the one unrecoverable mistake
    in the design.

    A skip looks recoverable because sealing the flat file destroys nothing and
    a revert unseals it. It is not. DWB-595's revert RENDERS THE STORE OVER THE
    FILE, and a skipped entry has no row in the store, so the revert overwrites
    the intact original with a version excluding exactly the content it was
    supposed to recover. The recovery path is the deletion.

    Every skip is journaled, noise and judgement alike. The transition
    vocabulary cannot tell those apart, and the journal is append-only, never
    auto-loaded and free until reached for, so a mis-read heading sitting in it
    costs essentially nothing while the alternative loses a real lesson.
    """
    row = _load(db, transition_id)
    body, heading_path = _body_of(row)

    note = body
    if heading_path:
        note = f"[{' / '.join(heading_path)}] {body}"
    if reason:
        note = f"{note}\n\nSkipped during adopt: {reason}"

    entry = JournalEntry(
        agent_id=row.agent_id,
        tags=list(SKIP_TAGS),
        body=note,
    )
    db.add(entry)
    # Flushed BEFORE the state moves, so a failure between the two leaves the
    # row non-terminal and the entry re-decidable, rather than terminal with its
    # content nowhere.
    db.flush()

    row.decided_by = decided_by
    row.reason = reason
    row.decided_at = _decision_now()
    row.state = TransitionState.skipped
    db.flush()
    return row


def decide_and_maybe_cut_over(
    db: Session,
    *,
    transition_id: int,
    tier: str | None,
    decided_by: str,
    reason: str | None = None,
) -> tuple[MemoryTransition, MemoryMode | None]:
    """One decision, then the cutover check. The caller's single entry point.

    `tier=None` means skip. Returns the row and the mode landed in, which is
    None unless this decision was the last one.

    The cutover is checked HERE rather than by a separate trigger because the
    TL ruled it fires on the last terminal row: the mode change is the pipeline
    finishing, not an act afterwards, and anything that needs an agent to decide
    to run it will eventually not be run.
    """
    from app.services import memory_cutover

    if tier is None:
        row = skip(db, transition_id=transition_id, decided_by=decided_by, reason=reason)
    else:
        row = decide(
            db,
            transition_id=transition_id,
            tier=tier,
            decided_by=decided_by,
            reason=reason,
        )

    agent = db.get(Agent, row.agent_id)
    project = db.get(Project, agent.project_id) if agent else None
    landed = (
        memory_cutover.complete_if_finished(db, project) if project is not None else None
    )
    return row, landed
