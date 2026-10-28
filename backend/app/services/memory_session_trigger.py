# Path: app/services/memory_session_trigger.py
# File: memory_session_trigger.py
# Created: 2026-10-08 (DWB-650)
# Purpose: Turn "a DWB session opened" into "every agent on that project is
#          consolidated", without anyone being told to do anything. Owns the
#          never-fail guard around the roster pass and the record that makes a
#          failure readable instead of silent.
# Caller: app/services/dwb_session.open_session (the one chokepoint every
#         session-open path goes through)
# Callees: app/services/memory_consolidate.consolidate_project_roster,
#          app/services/activity_log.log_activity, app/models/error_log
# Data In: db Session, project_id, the id of the session that just opened
# Data Out: RosterConsolidationResult, for tests and for the caller to read
# Last Modified: 2026-10-28 (DWB-707: the memory_consolidation_pass payload
#                carries concluded_nominated / concluded_unfinished)
#                (DWB-650)

"""The session-open consolidation trigger (DWB-650).

WHY THIS IS NOT A HOOK, A SLASH COMMAND OR A PLAYBOOK LINE. Miles's constraint,
verbatim: "this is programmatic. dwb sesh launch does this, no one has to
remember." The mechanism this replaces failed that test - it hung off a Claude
Code SessionStart, which fires for one agent, and only for an agent whose
identity was already resolved. A subagent's marker is not renamed until its
first SubagentStop, so a subagent never produces a SessionStart row with an
agent attached and consolidation had never once run for one. Over seven days
across all projects: 275 SubagentStop hook_sessions, 10 SessionStart, and the
only two agents holding a SessionStart row were the two team leads.

So the trigger is `dwb_session.open_session` itself, and it is called from
INSIDE that function rather than from the router. The router is one of three
callers - `routers/dwb_sessions.open_dwb_session`, and two hook paths in
`hook_tracking` that open a session from a matched phrase. Wiring the router
would leave the other two silent, and the next person to add a fourth opener
would have to know to wire it. Wiring the service means there is nothing to
know: opening a session IS running the pass, and no file anywhere needs a
sentence telling a human or an agent to trigger it.

THE RECORD, AND WHY A LOG LINE IS NOT ONE. Constraint 2 of the ticket is
DWB-636: the existing call site catches every exception, logs, and continues,
so a consolidation that blew up is indistinguishable from one that moved
nothing. A `logger.exception` call is not a fix for that - it goes to a file
nobody reads next to a dashboard that shows nothing, and the ABSENCE of a
failure and the absence of any record look identical from the API.

Two durable rows are written instead, and the pair is the point:

  1. ONE `activity_log` row per pass, on every human_memory open, whether or
     not anything moved and whether or not anything failed. It carries the
     arithmetic: how many agents were attempted, how many succeeded, how many
     failed. A clean pass is `failed: 0` and is POSITIVELY recorded, so "it ran
     and was quiet" has a row and "it never ran" has none. That is the
     distinction DWB-636 says does not currently exist.
  2. ONE `error_logs` row per failed agent, carrying the exception and the
     agent it belongs to, so the errors panel shows the failure with a name
     attached rather than an operator having to infer it from a gap.

THE OPEN STILL CANNOT FAIL. Constraint 1. Every failure mode here is contained:
per-agent failures are isolated by savepoints inside
`consolidate_project_roster`, and this module wraps the whole thing in one more
guard for the catastrophic case (the roster query itself failing, say). That
outer guard is a swallow in the same shape as the one DWB-636 complains about,
with one difference that matters: it tries to leave a row behind, and if even
that fails it degrades to the logger rather than to nothing. A guard that can
leave no trace is the defect; a guard that leaves a trace whenever a trace can
be written is the best available.

IDEMPOTENCE IS INHERITED, NOT ADDED. `open_session` returns `(None, existing)`
before it creates anything when a session is already open, so a double-open and
the 409 path never reach this module at all - there is no second pass to make
idempotent. The movements themselves are also each individually idempotent
(every one acts on a threshold it re-reads), but this path does not rely on
that, and a test asserts the 409 case runs nothing.
"""

import logging

from sqlalchemy.orm import Session

from app.models.error_log import ErrorLog, ErrorSource
from app.services import memory_consolidate
from app.services.activity_log import log_activity

logger = logging.getLogger(__name__)

ACTIVITY_ACTION = "memory_consolidation_pass"
"""The activity_log `action` for one roster pass. Fits String(50)."""

ACTIVITY_ENTITY_TYPE = "session"
"""Logged against the DWB session that triggered it, so the pass appears on the
session it belongs to rather than floating free on the project."""

ERROR_ENDPOINT = "dwb_session.open_session"
ERROR_TYPE = "ConsolidationFailed"


def on_session_opened(
    db: Session, *, project_id: int, dwb_session_id: int
) -> memory_consolidate.RosterConsolidationResult:
    """Consolidate every agent on `project_id`. Never raises. Does not commit.

    Returns the roster result so a caller or a test can read what happened. The
    return value is informational: `open_session` ignores it, because there is
    no outcome here that should change whether a session opens.

    Does not commit, deliberately. The caller owns the transaction, and tying
    the pass to the session row's own commit is what makes the activity_log
    record honest - if the open rolls back, the claim that a pass ran rolls back
    with it, rather than surviving as a record of work that was undone.
    """
    try:
        # THE OUTER SAVEPOINT IS NOT BELT-AND-BRACES OVER THE PER-AGENT ONES.
        # Those only contain a failure RAISED INSIDE `consolidate_agent`. A
        # failure in the roster query itself, or anywhere else in the fan-out,
        # happens outside them and leaves the transaction in a state where the
        # caller's commit would raise - which would fail the session open, the
        # one thing constraint 1 forbids. Rolling back to here keeps the session
        # row valid and loses only this pass's work, which is the right trade
        # when the pass cannot be trusted anyway.
        with db.begin_nested():
            result = memory_consolidate.consolidate_project_roster(
                db, project_id=project_id
            )
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        # The catastrophic case: the roster query itself failed, or something
        # outside any per-agent savepoint did. The session open must survive it.
        logger.exception(
            "DWB-650 roster consolidation failed entirely for project_id=%s "
            "dwb_session_id=%s",
            project_id,
            dwb_session_id,
        )
        _record_error(
            db,
            project_id=project_id,
            agent_id=None,
            message=(
                f"Roster consolidation failed before any agent was attempted: "
                f"{type(exc).__name__}: {exc}"
            ),
        )
        return memory_consolidate.RosterConsolidationResult(
            project_id=project_id, reason="roster_pass_raised"
        )

    if not result.ran:
        # A stock project. Nothing ran and nothing should have; recording a pass
        # here would make the feed claim work that was correctly declined.
        return result

    _record_pass(db, result=result, dwb_session_id=dwb_session_id)
    for outcome in result.failed:
        _record_error(
            db,
            project_id=project_id,
            agent_id=outcome.agent_id,
            message=(
                f"Consolidation failed for agent {outcome.agent_name} "
                f"(id={outcome.agent_id}) at DWB session open "
                f"(dwb_session_id={dwb_session_id}): {outcome.error}"
            ),
        )
    return result


def _record_pass(
    db: Session,
    *,
    result: memory_consolidate.RosterConsolidationResult,
    dwb_session_id: int,
) -> None:
    """One activity_log row describing the pass, failures included.

    `agent_id=None`: a roster pass belongs to the project, not to any one agent,
    and attributing it to the opener would reintroduce in the record the exact
    single-agent framing this ticket removes from the behaviour.
    """
    details = {
        "trigger": "dwb_session_open",
        "dwb_session_id": dwb_session_id,
        "agents_attempted": result.attempted,
        "agents_succeeded": result.succeeded,
        "agents_failed": len(result.failed),
        "moved_anything": result.moved_anything,
        # Named, not just counted. An operator reading "1 failed" still has to
        # go looking; the name is what turns the row into something actionable
        # on its own.
        "failed_agents": [o.agent_name for o in result.failed],
        "tiered_raw": sum(
            len(o.result.tiered_raw) for o in result.outcomes if o.result
        ),
        "promoted_scars": sum(
            len(o.result.promoted_scars) for o in result.outcomes if o.result
        ),
        "evicted_working": sum(
            len(o.result.evicted_working) for o in result.outcomes if o.result
        ),
        "concluded_scars": sum(
            len(o.result.concluded_scars) for o in result.outcomes if o.result
        ),
        # DWB-707. `concluded_scars: 0` alone cannot say WHY it is zero, and
        # the two reasons call for opposite responses: nominated 0 means the
        # resting-score gate let nothing through and the lane is idle;
        # nominated N with 0 concluded means the lane ran and every context
        # was still live. Fourteen consecutive passes logged the first while
        # being indistinguishable from the second. Both counts ride the
        # existing `memory_consolidation_pass` payload rather than a new
        # surface, because that payload is already served by
        # GET /api/projects/{id}/activity-feed, which is somewhere a human
        # already looks.
        "concluded_nominated": sum(
            o.result.concluded_nominated for o in result.outcomes if o.result
        ),
        "concluded_unfinished": sum(
            o.result.concluded_unfinished for o in result.outcomes if o.result
        ),
        "promoted_journal": sum(
            len(o.result.promoted_journal) for o in result.outcomes if o.result
        ),
    }
    try:
        # Savepointed for the same reason `_record_error` is: `log_activity`
        # flushes, and a flush that fails here would poison the transaction the
        # session row is sitting in. Recording the pass must never be the thing
        # that stops the session opening.
        with db.begin_nested():
            log_activity(
                db,
                result.project_id,
                None,
                ACTIVITY_ENTITY_TYPE,
                dwb_session_id,
                ACTIVITY_ACTION,
                details,
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "DWB-650 could not record the consolidation pass for project_id=%s",
            result.project_id,
        )


def _record_error(
    db: Session, *, project_id: int, agent_id: int | None, message: str
) -> None:
    """One error_logs row for a failure, written in its own savepoint.

    THE SAVEPOINT IS THE WHOLE REASON THIS IS A FUNCTION. The failure being
    recorded may have left the transaction in a state where a further write
    fails too, and an error record that disappears along with the error is worse
    than no record at all - it reads as a clean pass, which is DWB-636 exactly.
    The nested block contains that, and the logger is the last resort below it.
    """
    try:
        with db.begin_nested():
            db.add(
                ErrorLog(
                    project_id=project_id,
                    agent_id=agent_id,
                    source=ErrorSource.backend,
                    endpoint=ERROR_ENDPOINT,
                    error_type=ERROR_TYPE,
                    message=message,
                    function_name="on_session_opened",
                )
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "DWB-650 could not record a consolidation failure for project_id=%s "
            "agent_id=%s (original failure: %s)",
            project_id,
            agent_id,
            message,
        )
