# Path: app/services/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Project CRUD with overhead increment and cascading delete, plus the
#          DWB-588 memory_mode switch guard and its verbatim warning copy
# Caller: app/routers/projects.py
# Callees: app/models/project.py and all related models
# Data In: db: Session, ProjectCreate/Update
# Data Out: list[Project], Project, MEMORY_MODE_SWITCH_WARNING,
#           memory_mode_transition_refusal() -> str | None
# Last Modified: 2026-10-07 (DWB-637: the adoption BEGIN-edge session guard is
#                now defence in depth behind memory_origin's per-insert rule;
#                its comment records that, and the guard itself is unchanged;
#                previously DWB-624: complete the child enumeration and
#                journal memories whose clock origin the teardown destroys;
#                previously DWB-624: complete the delete_project child
#                enumeration - nodes, node_pointers, node_exclusions,
#                standards_audit, and the session-linked memory rows)

from datetime import datetime, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.agent import Agent
from app.models.agent_consolidation_ack import AgentConsolidationAck
from app.models.agent_score import AgentScore
from app.models.alert import Alert
from app.models.comment import Comment
from app.models.dwb_session import DwbSession
from app.models.epic import Epic
from app.models.failure_record import FailureRecord
from app.models.hook_session import HookSession
from app.models.instruction import Instruction
from app.models.agent_memory import AgentMemory
from app.models.agent_memory import MemoryTier
from app.models.journal_entry import JournalEntry
from app.models.node import Node, NodePointer
from app.models.node_exclusion import NodeExclusion
from app.models.memory_transition import (
    TERMINAL_STATES,
    MemoryTransition,
    MemoryTransitionRun,
    TransitionDirection,
    TransitionRunState,
    TransitionState,
)
from app.models.project import MemoryMode, Project, ProjectStatus
from app.models.project_agent import ProjectAgent
from app.models.score_event import ScoreEvent
from app.models.sprint import Sprint
from app.models.standards_audit import StandardsAudit
from app.models.status_history import StatusHistory
from app.models.test_result import TestResult
from app.models.ticket import Ticket
from app.models.inter_agent_message import InterAgentMessage
from app.models.tl_message import TlMessage
from app.models.tool_action import ToolAction
from app.models.tracking_log import TrackingLog
from app.services import journal as journal_svc
from app.schemas.project import ProjectCreate, ProjectUpdate


# DWB-624: tags on every journal entry this teardown writes, so a human reading
# the journal later sees why the entry arrived without joining back to a
# project row that no longer exists. Same precedent as
# memory_scar_conclude.CONCLUDED_TAGS and memory_evict.EVICTION_TAGS.
ORIGIN_LOST_TAGS = ["project-deleted", "origin-lost"]


def list_projects(db: Session, status: ProjectStatus | None = None) -> list[Project]:
    stmt = select(Project)
    if status:
        stmt = stmt.where(Project.status == status)
    stmt = stmt.order_by(Project.created_at.desc())
    return list(db.scalars(stmt).all())


def get_project(db: Session, project_id: int) -> Project | None:
    return db.get(Project, project_id)


def create_project(db: Session, data: ProjectCreate) -> Project:
    project = Project(**data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


# ---------------------------------------------------------------------------
# DWB-588: the memory_mode switch guard.
#
# THIS STRING IS MILES'S OWN COPY, VERBATIM from docs/human_memory_spec.md
# section 6. Do not reword it, do not tidy it, do not "improve" it.
#
# ALL MARKUP IS DELIBERATELY EXCLUDED: no bold, no italics, no backticks, and
# not the spec's leading warning icon (no icons in UI copy, a standing rule).
# One rule, so nobody has to guess which marks survive: THE CONSTANT CARRIES
# THE WORDS, THE UI CARRIES THE PRESENTATION. "Verbatim" here protects the
# wording, which is what could mislead someone; an absent backtick cannot.
# Do not add the backticks back as a fix.
#
# It lives here, as the single source of truth, for two reasons. The test
# compares the API response against THIS constant rather than reading the spec
# at runtime, because a test that parses the doc inverts the source of truth
# and turns any doc edit into a red suite. And the frontend renders whatever
# the API hands back rather than keeping its own copy, because a second copy
# is the thing that drifts.
# ---------------------------------------------------------------------------

MEMORY_MODE_SWITCH_WARNING = (
    "Switching memory modes rewrites every memory this project has.\n"
    "\n"
    "human_memory stores memory in a completely different structure, under "
    "different rules, with a different lifecycle. Switching is not a migration "
    "you can run and walk away from: every existing memory has to be re-read "
    "and re-tiered, and that is a judgment call an agent makes one entry at a "
    "time. It costs real time and real tokens, and switching back costs them "
    "again and loses the tiering.\n"
    "\n"
    "Decide this at the start of a project.\n"
    "\n"
    "We'll let you do it... but think it thru this time, sport."
)


# ---------------------------------------------------------------------------
# DWB-593: the memory_mode STATE MACHINE.
#
# THE BUG THIS CLOSES. A direct flip to `human_memory` sealed the flat file
# (DWB-589) against an empty store, so every agent on the project spawned
# amnesiac until someone flipped it back. Reversible, but a silent outage while
# it lasted.
#
# THE FIX IS NOT A SOFTER SEAL. The seal does exactly what DWB-589 specified,
# and that was correct for a flag nobody could flip without a migration behind
# it. What was missing is that nothing enforced that precondition. So the fix
# makes the state the seal fires in UNREACHABLE. Anyone who reads this as "the
# seal was too eager" and adds exceptions to it has built a seal that leaks on
# a path nobody tested, which is worse than the bug: hard rule 1 exists to stop
# two memories both looking authoritative.
# ---------------------------------------------------------------------------

BEGIN = "begin"
CUTOVER = "cutover"
ABORT = "abort"

LEGAL_MEMORY_MODE_EDGES: dict[tuple[MemoryMode, MemoryMode], str] = {
    (MemoryMode.stock, MemoryMode.adopting): BEGIN,
    (MemoryMode.adopting, MemoryMode.human_memory): CUTOVER,
    (MemoryMode.human_memory, MemoryMode.reverting): BEGIN,
    (MemoryMode.reverting, MemoryMode.stock): CUTOVER,
    # Aborts, back to where the transition came from. An operator who starts
    # adopting and changes their mind must not have to complete a migration to
    # get out (TL ruling, 2026-09-30).
    (MemoryMode.adopting, MemoryMode.stock): ABORT,
    (MemoryMode.reverting, MemoryMode.human_memory): ABORT,
}
"""Every legal edge, as data rather than as branches.

`(stock, human_memory)` IS DELIBERATELY ABSENT and its absence is the bug fix.
The only route into human_memory is through `adopting`, which is the state that
does the work while stock stays authoritative.

A dict rather than if/elif because adding a state should force a decision about
every edge it participates in, and an unlisted pair refuses by default. The
dangerous direction of failure here is permitting an edge nobody considered.
"""


def open_run(db: Session, project_id: int) -> MemoryTransitionRun | None:
    """The project's in-flight transition, or None.

    At most one can exist: the database enforces it with a STORED generated
    column plus a composite UNIQUE, rather than a read-check-write here, which
    would race.
    """
    return db.scalar(
        select(MemoryTransitionRun)
        .where(MemoryTransitionRun.project_id == project_id)
        .where(MemoryTransitionRun.state == TransitionRunState.open)
    )


def non_terminal_transitions(db: Session, project_id: int) -> list[MemoryTransition]:
    """Rows that must finish before a cutover may proceed, oldest first."""
    return list(
        db.execute(
            select(MemoryTransition)
            .where(MemoryTransition.project_id == project_id)
            .where(MemoryTransition.state.notin_(list(TERMINAL_STATES)))
            .order_by(MemoryTransition.id.asc())
        )
        .scalars()
        .all()
    )


def _cutover_blocked_message(rows: list[MemoryTransition]) -> str:
    """Name WHAT is blocking, not merely THAT something is.

    A refusal that says only "not ready" leaves the operator with no next
    action, which is how a guard becomes something people work around. This
    names the agents, the counts and the states.
    """
    by_agent: dict[int, dict[str, int]] = {}
    for row in rows:
        by_agent.setdefault(row.agent_id, {})
        state = row.state.value
        by_agent[row.agent_id][state] = by_agent[row.agent_id].get(state, 0) + 1

    lines = [
        f"Cutover refused: {len(rows)} memory transition "
        f"{'entry is' if len(rows) == 1 else 'entries are'} still in flight "
        f"across {len(by_agent)} agent{'' if len(by_agent) == 1 else 's'}.",
        "",
        "Every entry must reach a terminal state (written, skipped or "
        "journaled) before the mode can change. Still outstanding:",
    ]
    for agent_id in sorted(by_agent):
        detail = ", ".join(
            f"{count} {state}" for state, count in sorted(by_agent[agent_id].items())
        )
        lines.append(f"  agent {agent_id}: {detail}")
    return "\n".join(lines)


def memory_mode_transition_refusal(
    db: Session, project: Project, data: ProjectUpdate
) -> str | None:
    """The reason to refuse this memory_mode change, or None to allow it.

    Three gates, in order, and the order matters: an illegal edge is refused
    before anything is counted, so an operator attempting the old direct flip
    gets told the route rather than a report on transition rows that are
    irrelevant to it.
    """
    if "memory_mode" not in data.model_fields_set:
        return None
    target = data.memory_mode
    if target is None or target == project.memory_mode:
        # A no-op cannot rewrite anything, and an explicit null is not a switch.
        return None

    edge = LEGAL_MEMORY_MODE_EDGES.get((project.memory_mode, target))
    if edge is None:
        return _illegal_edge_message(project.memory_mode, target)

    # The spec's warning guards BEGINNING to switch, which is the act that
    # commits to re-reading and re-tiering every entry. A cutover or an abort
    # is the continuation of a decision already confirmed once, so re-asking
    # would train the operator to click through it.
    if edge == BEGIN and not data.memory_mode_confirmed:
        return MEMORY_MODE_SWITCH_WARNING

    if edge == BEGIN and target == MemoryMode.adopting:
        # AN ADOPTION WITH NO OPEN SESSION MINTS A STORE THAT CANNOT BE READ,
        # AND THIS HAS NOW HAPPENED TWICE.
        #
        # `memory_decide.decide` USED TO STAMP `created_session_id` from
        # whatever `get_active_session` returned, including None. That rule was
        # held to be correct where it came from - the raw write path ruled that
        # a lesson with no origin beats a lesson lost - but adoption inherited
        # it and at bulk scale it inverted. (Past tense since DWB-637: both
        # writers now refuse rather than stamping NULL. Kept because it is why
        # this guard exists, and a reader who meets it in the present tense will
        # go looking for a fallback that is no longer there.) A row with neither
        # `created_session_id` nor
        # `last_reinforced_session_id` cannot be scored;
        # `memory_score.scored_memory` excludes unscoreable rows from every
        # candidate list, so `memory_context.assemble_session_context` returns
        # empty and `memory_mode.memory_full_for` falls through to the sealed
        # pointer. The flat file is sealed behind the mode by then, so there is
        # no fallback: every agent on the project spawns amnesiac with a full
        # store sitting behind it.
        #
        # The first occurrence (396 rows) is described in a comment above that
        # `get_active_session` call and was closed as "an omission on ONE
        # writer, not a missing capability". It recurred on the next migration
        # - 293 of 295 rows on IND - because a comment is not a guard. This is
        # the guard.
        #
        # DWB-637: THIS GUARD IS NOW DEFENCE IN DEPTH, NOT THE ONLY GUARD, AND
        # THE PARAGRAPH BELOW IS WHY IT WAS NOT ENOUGH ON ITS OWN.
        #
        # It stays because it is the only guard the OPERATOR sees, at the only
        # moment they are present, and a refusal here costs them one command
        # where a refusal 200 decisions in costs an agent its run. But it is no
        # longer what keeps a NULL origin out of the table. That is
        # `memory_origin.require_session_origin`, called at every site that
        # inserts into `agent_memories`, which closes the hole this one
        # structurally cannot: this runs ONCE, at the flip, and the stamp runs
        # PER DECISION, so a session closing mid-run walked straight past it.
        #
        # REFUSED AT BEGIN rather than per-decision, for two reasons. The
        # operator is present at exactly this moment and nowhere later, and
        # enumeration has not run yet, so nothing has to be unwound. Refusing
        # the 1st of 308 decisions would strand a half-judged run instead.
        # (DWB-637 settled that trade the other way for the per-decision case:
        # a stranded run is re-decidable in one call, where a run that finishes
        # with NULL origins is not recoverable without a backfill.)
        #
        # `created_session_id` is an FK to `dwb_sessions`, so there is no
        # synthetic origin to stamp instead - the session has to genuinely
        # exist. Hence a precondition rather than a fallback.
        #
        # ADOPTION ONLY. `reverting` also travels a BEGIN edge and does not
        # mint memory rows: DWB-595's revert renders the store back over the
        # flat file, so it has no origin to lose.
        from app.services import dwb_session as session_svc

        if session_svc.get_active_session(db, project.id) is None:
            return (
                f"Adoption refused: {project.prefix} has no open DWB session.\n"
                "\n"
                "Every memory this adoption writes stamps its clock origin "
                "from the session open at the time. With none open, all of "
                "them store NULL, and a memory with no origin cannot be "
                "scored - so it is excluded from retrieval and never reaches "
                "an agent. The store would fill up and read as empty, with "
                "the flat file sealed behind the mode and no fallback.\n"
                "\n"
                "Open a session first (/dwb-open, or POST /api/sessions/open) "
                "and start the adoption again."
            )

    if edge == CUTOVER:
        run = open_run(db, project.id)
        if run is None:
            # A transition state with no run behind it. Reachable only if the
            # column were edited directly, but refusing is the safe direction:
            # the alternative is cutting over with nothing known about what was
            # meant to move.
            return (
                f"Cutover refused: {project.prefix} is marked "
                f"{project.memory_mode.value} but has no open transition run. "
                "Abort back to the previous mode and start again."
            )
        if run.enumerated_at is None:
            # THE PRECONDITION THE FIRST VERSION OF THIS GUARD WAS MISSING, and
            # the bug it lets through is the one this whole ticket exists to
            # prevent. Without it, stock -> adopting -> human_memory sealed the
            # flat file against an empty store in two calls, because "no
            # unfinished entries" is trivially true when there are NO entries.
            #
            # Zero entries cannot distinguish "enumeration ran and found
            # nothing", which is a legitimate cutover for a project with no
            # memory, from "enumeration never ran", which is the outage. A
            # count cannot tell them apart; this timestamp can.
            return (
                "Cutover refused: the entries for this transition have not been "
                "enumerated yet, so there is nothing to confirm has moved.\n"
                "\n"
                "Cutting over now would seal stock memory against a store that "
                "was never populated, which is the outage this pipeline exists "
                "to prevent. Run the enumeration first; it is what decides "
                "whether this project has entries to move or genuinely has "
                "none."
            )
        blocking = non_terminal_transitions(db, project.id)
        if blocking:
            return _cutover_blocked_message(blocking)

    return None


def _illegal_edge_message(current: MemoryMode, target: MemoryMode) -> str:
    routes = ", ".join(
        f"{a.value} -> {b.value}"
        for (a, b) in LEGAL_MEMORY_MODE_EDGES
        if a == current
    ) or "none"
    extra = ""
    if current == MemoryMode.stock and target == MemoryMode.human_memory:
        extra = (
            "\n\nGoing straight to human_memory is what this refusal exists to "
            "prevent. It used to be allowed, and it sealed stock memory against "
            "an empty store: every agent on the project spawned with no memory "
            "until the mode was flipped back. Start with `adopting`, which "
            "moves entries across while stock stays authoritative, then cut "
            "over once every entry has landed."
        )
    return (
        f"memory_mode cannot go from {current.value} to {target.value}.\n"
        f"Legal moves from {current.value}: {routes}.{extra}"
    )


def abort_transition(db: Session, project: Project) -> int:
    """Wind back a transition. Returns the number of rows marked skipped.

    DELETES THE agent_memories ROWS THIS TRANSITION WROTE, and that is not a
    hard rule 4 violation. Rule 4 protects content LEAVING memory; these never
    ENTERED it. During `adopting` stock is authoritative and anything staged in
    agent_memories is inert - nothing reads it - while the source still sits
    untouched in the flat file. Deleting staging loses nothing.

    Leaving it would be the harmful choice: a later adopt would find a
    half-populated store with no way to tell which rows were real.
    """
    # WRITTEN ROWS ARE WOUND BACK TOO, not just the unfinished ones, and that
    # is the difference between an honest record and a plausible one. Their
    # product is deleted below, so a row left saying `written` would claim an
    # entry landed while its memory no longer exists. First version of this
    # did exactly that and the row set read {written: 1, skipped: 2}, which is
    # a lie the next reader has no way to detect.
    #
    # `journaled` rows are NOT wound back: a journaled entry left as an episode
    # and that content is real and was never deleted. `skipped` rows are
    # already where they belong.
    rows = list(
        db.execute(
            select(MemoryTransition)
            .where(MemoryTransition.project_id == project.id)
            .where(
                MemoryTransition.state.notin_(
                    [TransitionState.journaled, TransitionState.skipped]
                )
            )
            .order_by(MemoryTransition.id.asc())
        )
        .scalars()
        .all()
    )
    staged = [r.target_memory_id for r in rows if r.target_memory_id is not None]

    now = datetime.now(timezone.utc)
    run = open_run(db, project.id)
    if run is not None:
        run.state = TransitionRunState.aborted
        run.aborted_at = now
    for row in rows:
        row.state = TransitionState.skipped
        row.decided_at = row.decided_at or now
    # Break the FK before deleting what it points at.
    db.execute(
        update(MemoryTransition)
        .where(MemoryTransition.project_id == project.id)
        .values(target_memory_id=None)
    )
    if staged:
        db.execute(delete(AgentMemory).where(AgentMemory.id.in_(set(staged))))
    return len(rows)


# DWB-588's `memory_mode_switch_refusal` WAS HERE AND IS DELETED (DWB-593).
#
# Removed rather than left unused, and the distinction matters. It did not
# merely lose its caller: it IMPLEMENTS THE RULE THIS TICKET EXISTS TO FORBID.
# Given `memory_mode_confirmed`, it returned None for a direct
# stock -> human_memory switch, which is the flip that sealed the flat file
# against an empty store and left every agent on the project amnesiac.
#
# So it is not dead code, it is a loaded one. Anything that called it would
# reintroduce the outage while looking like it was consulting a guard, and it
# would read as the older and therefore more settled of the two functions.
#
# Its replacement is `memory_mode_transition_refusal` below, which checks edge
# legality FIRST, then confirmation on BEGIN edges only, then the cutover
# precondition. MEMORY_MODE_SWITCH_WARNING survives and is still the body of
# the confirmation refusal; only the function that applied it too liberally is
# gone.


def _enumerate_for_run(
    db: Session, project: Project, run: MemoryTransitionRun, target: MemoryMode
) -> MemoryMode | None:
    """Run DWB-594's enumeration for a freshly opened run.

    Returns the mode to land in INSTEAD of `target` when the project has no
    candidates at all, or None to stay in the transition state.

    FAILS CLOSED IF THE ENUMERATOR IS ABSENT, and that is deliberate rather
    than defensive. If the module is not importable, `enumerated_at` stays NULL
    and the cutover guard refuses, so the worst case is a project stuck in
    `adopting` with a refusal that says why. The alternative - treating a
    missing enumerator as "nothing to enumerate" - would set enumerated_at and
    wave through a cutover into an empty store, which is the original bug
    arriving through the repair.
    """
    try:
        from app.services import memory_adopt
    except ImportError:
        return None

    enumerate_fn = getattr(memory_adopt, "enumerate_for_run", None)
    if enumerate_fn is None:
        return None

    written = enumerate_fn(db, project=project, run=run)
    run.enumerated_at = datetime.now(timezone.utc)
    db.flush()

    if written:
        return None

    # Nothing to move. Close the run and land on the far side, so no project
    # ever rests in a transition state with zero entries.
    run.state = TransitionRunState.completed
    run.completed_at = datetime.now(timezone.utc)
    return (
        MemoryMode.human_memory
        if target == MemoryMode.adopting
        else MemoryMode.stock
    )


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    fields = data.model_dump(exclude_unset=True)
    # DWB-593: an abort winds back its own staging before the mode moves, so
    # the project never rests in a state where the store holds rows nothing
    # reads and nothing will finish.
    target = fields.get("memory_mode")
    if target is not None and target != project.memory_mode:
        edge = LEGAL_MEMORY_MODE_EDGES.get((project.memory_mode, target))
        if edge == BEGIN:
            run = MemoryTransitionRun(
                project_id=project.id,
                direction=(
                    TransitionDirection.adopt
                    if target == MemoryMode.adopting
                    else TransitionDirection.revert
                ),
                state=TransitionRunState.open,
            )
            db.add(run)
            db.flush()
            # DWB-594 enumerates IN THIS REQUEST AND THIS TRANSACTION, by TL
            # ruling. Not a separate trigger: a separate trigger leaves a
            # window where the project is `adopting` with no rows, which is the
            # state Freddie's overlay cannot render and the cutover guard
            # cannot distinguish from a finished-and-empty one. Miles's
            # constraint is the one that settles it - anything needing an agent
            # to decide to run it will eventually not be run.
            target_mode = _enumerate_for_run(db, project, run, target)
            if target_mode is not None:
                # Zero candidates: the project has nothing to move, so it must
                # not rest in `adopting`. It walks BEGIN then CUTOVER inside
                # this one request rather than jumping, so the legal-edge table
                # still governs every step and `stock -> human_memory` stays
                # absent from it as an externally reachable edge.
                fields["memory_mode"] = target_mode
        elif edge == CUTOVER:
            run = open_run(db, project.id)
            if run is not None:
                run.state = TransitionRunState.completed
                run.completed_at = datetime.now(timezone.utc)
        elif edge == ABORT:
            abort_transition(db, project)
    # DWB-588: memory_mode_confirmed is a request flag, not a column. The loop
    # below setattrs every key it is handed, so leaving it in would hang a
    # phantom attribute off the ORM instance.
    fields.pop("memory_mode_confirmed", None)
    for key, value in fields.items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


def increment_overhead(db: Session, project: Project, role: str, tokens_used: int, time_spent_seconds: int = 0) -> Project:
    if role == "team_lead":
        project.tl_overhead_tokens += tokens_used
        project.tl_overhead_time_seconds += time_spent_seconds
    elif role == "pm":
        project.pm_overhead_tokens += tokens_used
        project.pm_overhead_time_seconds += time_spent_seconds
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    pid = project.id
    # Get all ticket IDs for this project to delete child records
    ticket_ids = list(
        db.scalars(select(Ticket.id).where(Ticket.project_id == pid)).all()
    )
    # Get all sprint IDs to clear sprint-scoped child rows (consolidation acks)
    sprint_ids = list(
        db.scalars(select(Sprint.id).where(Sprint.project_id == pid)).all()
    )
    if ticket_ids:
        # Delete comments on project tickets
        db.execute(delete(Comment).where(Comment.ticket_id.in_(ticket_ids)))
        # Delete alerts linked to project tickets
        db.execute(delete(Alert).where(Alert.ticket_id.in_(ticket_ids)))
        # Delete failure records referencing project tickets
        db.execute(delete(FailureRecord).where(FailureRecord.ticket_id.in_(ticket_ids)))
        # Delete status history for project tickets
        db.execute(delete(StatusHistory).where(StatusHistory.ticket_id.in_(ticket_ids)))
    # DWB-593: transition rows before the runs they point at, and both before
    # the project. Every FK to `projects` in this schema is NO ACTION, so a
    # table left out here does not fail loudly at the model - it 500s the
    # delete endpoint with an integrity error. Found by deleting a throwaway
    # project and getting a 500 rather than a 204.
    db.execute(delete(MemoryTransition).where(MemoryTransition.project_id == pid))
    db.execute(
        delete(MemoryTransitionRun).where(MemoryTransitionRun.project_id == pid)
    )
    # Delete failure records directly on project (ticket_id may be null)
    db.execute(delete(FailureRecord).where(FailureRecord.project_id == pid))
    # Delete alerts directly on project (ticket_id may be null)
    db.execute(delete(Alert).where(Alert.project_id == pid))
    # Delete test results (may reference sprints/tickets in this project)
    db.execute(delete(TestResult).where(TestResult.project_id == pid))
    # Delete tracking logs
    db.execute(delete(TrackingLog).where(TrackingLog.project_id == pid))
    # Delete activity logs
    db.execute(delete(ActivityLog).where(ActivityLog.project_id == pid))
    # Delete instructions
    db.execute(delete(Instruction).where(Instruction.project_id == pid))
    # DWB-624: the node graph and the audit log. All three node tables carry a
    # NOT NULL project_id FK with NO ACTION, so any one of them left behind
    # 500s the endpoint. node_pointers is cleared explicitly rather than left
    # to its ON DELETE CASCADE from nodes, because it ALSO holds its own
    # project_id FK: a pointer whose node lives on another project would block
    # the delete even after every node here is gone.
    db.execute(delete(NodePointer).where(NodePointer.project_id == pid))
    db.execute(delete(Node).where(Node.project_id == pid))
    db.execute(delete(NodeExclusion).where(NodeExclusion.project_id == pid))
    # standards_audit rows linked to a ticket cascade with that ticket below,
    # but a row with a null ticket_id has only its project_id and blocks.
    db.execute(delete(StandardsAudit).where(StandardsAudit.project_id == pid))
    # DWB-424/425: clear the scoring ledger + derived cache before the sprints
    # and project they reference are deleted (no ON DELETE CASCADE on these FKs).
    db.execute(delete(ScoreEvent).where(ScoreEvent.project_id == pid))
    db.execute(delete(AgentScore).where(AgentScore.project_id == pid))
    # DWB-436: the cross-project team-lead channel. from_project_id is a NOT
    # NULL FK to projects, so messages SENT FROM this project must be deleted
    # before the project row goes (their read receipts cascade via the
    # message_id ON DELETE CASCADE). Messages sent TO this project's team-lead
    # from OTHER projects persist - their from_project_id points elsewhere and
    # the agent rows are only detached (NULLed project_id), never deleted.
    db.execute(delete(TlMessage).where(TlMessage.from_project_id == pid))
    # DWB-446: inter_agent_messages.project_id is a NOT NULL FK to projects and
    # dwb_session_id FKs dwb_sessions (no cascade), so clear by project before
    # both the dwb_sessions delete below and the project row go away.
    db.execute(
        delete(InterAgentMessage).where(InterAgentMessage.project_id == pid)
    )
    # DWB-417/421: tool_actions linked to this project's DWB sessions must go
    # before those sessions (the dwb_session_id FK has no cascade). Ticket-linked
    # tool_actions cascade with their tickets below; agent-linked-only rows have
    # no project FK and are left (agents are global, not deleted).
    dwb_session_ids = list(
        db.scalars(select(DwbSession.id).where(DwbSession.project_id == pid)).all()
    )
    if dwb_session_ids:
        db.execute(
            delete(ToolAction).where(ToolAction.dwb_session_id.in_(dwb_session_ids))
        )
    # Delete hook sessions (FK to project, sprints, dwb_sessions, tickets) before
    # those parents go away.
    db.execute(delete(HookSession).where(HookSession.project_id == pid))
    # DWB-624 (absorbing DWB-616): agent_memories and journal_entries carry NO
    # project_id at all, so they cannot appear in an enumeration of the tables
    # that reference `projects`. They reach this project only through
    # dwb_sessions, whose FKs are NO ACTION, and they block the session delete
    # immediately below.
    #
    # These are NULLED, not deleted. Agents are global identities and are
    # merely detached above rather than removed; their memory belongs to the
    # agent, not to the project, and an agent that also worked elsewhere would
    # otherwise lose lessons because an unrelated project was deleted. Nulling
    # drops only the session linkage, which is what is actually going away.
    if dwb_session_ids:
        # HARD RULE 4: nothing leaves memory without landing in the journal
        # first. Nulling both origins makes a row unscoreable, and an
        # unscoreable row is excluded from every candidate list and never
        # rendered to an agent again - it has effectively left memory even
        # though the row survives. So journal it BEFORE the nulling, carrying
        # its ORIGINAL created_at (DWB-605), because the lesson existed long
        # before this journal entry does.
        #
        # Only rows that LOSE scoreability qualify. A row reinforced on a
        # surviving project keeps that origin through the COALESCE in
        # memory_score.sessions_since_reinforced and stays scoreable, so it is
        # not leaving memory and must not be journalled. Measured: a row with
        # both origins here goes unscoreable; one reinforced elsewhere comes
        # out at score 10.
        #
        # `raw` is excluded because it is never scoreable in the first place
        # (memory_score.UNSCORED_UNTIERED precedes the origin check), so it is
        # not losing anything it currently has. It DOES lose future
        # scoreability once tiered, which is a real gap and is flagged to the
        # TL rather than decided here: journalling a pre-judgment row would put
        # unjudged content in the journal, which contradicts what `raw` means.
        doomed_memories = list(
            db.scalars(
                select(AgentMemory).where(
                    AgentMemory.tier != MemoryTier.raw,
                    or_(
                        AgentMemory.created_session_id.is_not(None),
                        AgentMemory.last_reinforced_session_id.is_not(None),
                    ),
                    or_(
                        AgentMemory.created_session_id.is_(None),
                        AgentMemory.created_session_id.in_(dwb_session_ids),
                    ),
                    or_(
                        AgentMemory.last_reinforced_session_id.is_(None),
                        AgentMemory.last_reinforced_session_id.in_(dwb_session_ids),
                    ),
                )
            ).all()
        )
        for memory in doomed_memories:
            journal_svc.create_entry(
                db,
                agent_id=memory.agent_id,
                body=memory.body,
                tags=list(ORIGIN_LOST_TAGS),
                created_at=memory.created_at,
            )
        # Flushed BEFORE the nulling, same reasoning as
        # memory_scar_conclude: a failure here leaves memory intact and the
        # journal merely early, never the reverse.
        db.flush()

        db.execute(
            update(AgentMemory)
            .where(AgentMemory.created_session_id.in_(dwb_session_ids))
            .values(created_session_id=None)
        )
        db.execute(
            update(AgentMemory)
            .where(AgentMemory.last_reinforced_session_id.in_(dwb_session_ids))
            .values(last_reinforced_session_id=None)
        )
        db.execute(
            update(JournalEntry)
            .where(JournalEntry.dwb_session_id.in_(dwb_session_ids))
            .values(dwb_session_id=None)
        )
    # Delete DWB sessions on this project
    db.execute(delete(DwbSession).where(DwbSession.project_id == pid))
    # Delete consolidation acks tied to this project's sprints before the sprints
    if sprint_ids:
        db.execute(
            delete(AgentConsolidationAck).where(
                AgentConsolidationAck.sprint_id.in_(sprint_ids)
            )
        )
    # Delete tickets
    db.execute(delete(Ticket).where(Ticket.project_id == pid))
    # Delete project agents (the membership join)
    db.execute(delete(ProjectAgent).where(ProjectAgent.project_id == pid))
    # Detach agents homed on this project. Agents are global identities (name is
    # unique system-wide and they may carry history on OTHER projects), so we
    # null their home project_id rather than delete them.
    db.execute(update(Agent).where(Agent.project_id == pid).values(project_id=None))
    # Delete sprints
    db.execute(delete(Sprint).where(Sprint.project_id == pid))
    # Delete epics
    db.execute(delete(Epic).where(Epic.project_id == pid))
    # Delete project
    db.delete(project)
    db.commit()
