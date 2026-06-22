# Path: app/services/scoring_triggers.py
# File: scoring_triggers.py
# Created: 2026-06-22
# Purpose: Auto-trigger engine (DWB-425) - turn deterministic ticket / failure / sprint signals into score_event rows on the DWB-424 ledger. One place for all auto-scoring so the call sites in ticket/test_result/sprint services stay one-liners.
# Caller: app/services/ticket.py, app/services/test_result.py, app/services/sprint.py
# Callees: app/services/scoring.py (apply_score_event, event_exists_for_ref), app/services/tracking.py (compute_ticket_tokens), models (ticket, status_history, test_result, failure_record, sprint, agent, project_agent)
# Data In: db: Session, the triggering entity
# Data Out: ScoreEvent rows (via scoring.apply_score_event)
# Last Modified: 2026-06-22

"""Auto-trigger engine for agent scoring (DWB-425).

Each function maps one deterministic signal to a score_event on the DWB-424
ledger via ``scoring.apply_score_event``. Design rules:

- ATTRIBUTION is by domain ownership, never tool_actions session attribution:
  ticket triggers credit ``ticket.assigned_agent_id``; failure triggers credit
  the owning worker (``failure_record.agent_id`` for rework, the ticket's
  assignee for test failures).
- IDEMPOTENT: every event carries (ref_type, ref_id); callers guard with
  ``scoring.event_exists_for_ref`` so the same ticket / failure is never
  double-scored, even on repeated PATCHes or re-runs.
- MAGNITUDES come from app.config.scoring (tunable), never hardcoded.
- SPRINT-SCOPED: each event stamps the triggering entity's sprint_id so the
  per-sprint leaderboard delta populates.
- FOLD-IN: callers pass commit=False to fold the score write into the same
  transaction as the triggering change; the helper still flushes so the cache
  row updates atomically with the ledger row.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.scoring import points_for
from app.models.agent import Agent
from app.models.failure_record import FailureRecord
from app.models.project_agent import ProjectAgent
from app.models.score_event import ScoreSource, ScoreTriggerType
from app.models.sprint import Sprint
from app.models.status_history import StatusHistory
from app.models.test_result import TestResult
from app.models.ticket import Ticket
from app.services import scoring as scoring_svc
from app.services import tracking as tracking_svc

logger = logging.getLogger(__name__)


def _project_tl_agent_id(db: Session, project_id: int) -> int | None:
    return db.scalar(
        select(Agent.id)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
        .where(Agent.role == "team-lead")
        .limit(1)
    )


def score_ticket_closed(db: Session, ticket: Ticket, *, commit: bool = False) -> list[str]:
    """Score a ticket that just transitioned to done. Fires up to three events,
    all idempotent per ticket and attributed to ticket.assigned_agent_id:

      - ticket_closed: base award, plus the no_rework_bonus folded into the
        same delta when the ticket never had a rework failure record.
      - zero_token_close: penalty when no tokens were ever attributed to the
        ticket (tracking_log rollup == 0).
      - forgot: small penalty when a detectable hygiene signal is missed
        (never moved to in_progress; no test run recorded this sprint).

    Returns the list of trigger keys fired (for logging/tests).
    """
    agent_id = ticket.assigned_agent_id
    if not agent_id:
        return []  # nothing to attribute to

    pid = ticket.project_id
    sid = ticket.sprint_id
    fired: list[str] = []

    # --- ticket_closed (+ no_rework_bonus folded) ---
    if not scoring_svc.event_exists_for_ref(
        db, project_id=pid, subject_agent_id=agent_id,
        trigger_type=ScoreTriggerType.ticket_closed,
        ref_type="ticket", ref_id=ticket.id,
    ):
        base = points_for("ticket_closed")
        had_rework = db.scalar(
            select(FailureRecord.id)
            .where(FailureRecord.ticket_id == ticket.id)
            .where(FailureRecord.failure_type == "rework")
            .limit(1)
        ) is not None
        bonus = 0 if had_rework else points_for("no_rework_bonus")
        reason = f"closed {ticket.ticket_key} (+{base}"
        if bonus:
            reason += f", +{bonus} no-rework bonus"
        reason += ")"
        scoring_svc.apply_score_event(
            db, project_id=pid, subject_agent_id=agent_id, sprint_id=sid,
            trigger_type=ScoreTriggerType.ticket_closed, delta=base + bonus,
            source=ScoreSource.auto, reason=reason,
            ref_type="ticket", ref_id=ticket.id, commit=False,
        )
        fired.append("ticket_closed")

    # --- zero_token_close ---
    if not scoring_svc.event_exists_for_ref(
        db, project_id=pid, subject_agent_id=agent_id,
        trigger_type=ScoreTriggerType.zero_token_close,
        ref_type="ticket", ref_id=ticket.id,
    ):
        if tracking_svc.compute_ticket_tokens(db, ticket.id) == 0:
            scoring_svc.apply_score_event(
                db, project_id=pid, subject_agent_id=agent_id, sprint_id=sid,
                trigger_type=ScoreTriggerType.zero_token_close,
                delta=points_for("zero_token_close"), source=ScoreSource.auto,
                reason=f"{ticket.ticket_key} closed with 0 attributed tokens",
                ref_type="ticket", ref_id=ticket.id, commit=False,
            )
            fired.append("zero_token_close")

    # --- forgot (detectable hygiene misses) ---
    if not scoring_svc.event_exists_for_ref(
        db, project_id=pid, subject_agent_id=agent_id,
        trigger_type=ScoreTriggerType.forgot,
        ref_type="ticket", ref_id=ticket.id,
    ):
        reasons = _forgot_reasons(db, ticket)
        if reasons:
            scoring_svc.apply_score_event(
                db, project_id=pid, subject_agent_id=agent_id, sprint_id=sid,
                trigger_type=ScoreTriggerType.forgot,
                delta=points_for("forgot"), source=ScoreSource.auto,
                reason=f"{ticket.ticket_key}: " + "; ".join(reasons),
                ref_type="ticket", ref_id=ticket.id, commit=False,
            )
            fired.append("forgot")

    if commit and fired:
        db.commit()
    return fired


def _forgot_reasons(db: Session, ticket: Ticket) -> list[str]:
    """Detectable 'forgot' signals for a closed ticket.

    Implemented (derivable from captured DB state):
      - never moved to in_progress (worked silently / skipped the status)
      - no test run recorded this sprint before close

    NOT implemented (no captured data to derive from, deferred):
      - no commit referencing the key: commit refs are not persisted (git_hook
        closes tickets but stores no commit row), so this is undetectable today.
      - missing code header: a sprint-level signal covered by the force_headers
        gate (gate_miss), not cheaply derivable per-ticket.
    """
    reasons: list[str] = []

    moved_in_progress = db.scalar(
        select(StatusHistory.id)
        .where(StatusHistory.ticket_id == ticket.id)
        .where(StatusHistory.new_status == "in_progress")
        .limit(1)
    )
    if moved_in_progress is None:
        reasons.append("never moved to in_progress")

    sprint = db.get(Sprint, ticket.sprint_id) if ticket.sprint_id else None
    tr_stmt = select(TestResult.id).where(TestResult.project_id == ticket.project_id)
    if sprint and sprint.start_date:
        tr_stmt = tr_stmt.where(TestResult.run_at >= sprint.start_date)
    has_test_run = db.scalar(tr_stmt.limit(1)) is not None
    if not has_test_run:
        reasons.append("no test run recorded this sprint before close")

    return reasons


def score_failure_record(
    db: Session, failure_record: FailureRecord, *, commit: bool = False
):
    """Penalize an auto-detected failure. Maps failure_type -> trigger:

      - rework       -> rework penalty, subject = failure_record.agent_id (the
        worker; rework records always carry the ticket's assignee).
      - test_failure -> test_failure penalty, subject = the owning ticket's
        assignee. Skipped when the record has no ticket (the test_result path
        logs these against the tester with no ticket_id), so we never punish the
        tester who merely recorded the failure.
      - any manual (A-G) type -> no auto-score (human taxonomy, out of scope).

    Idempotent per failure_record. Returns the ScoreEvent or None when skipped.
    """
    ft = failure_record.failure_type
    if ft == "rework":
        subject = failure_record.agent_id
        trigger = ScoreTriggerType.rework
        key = "rework"
        label = "rework"
    elif ft == "test_failure":
        subject = None
        if failure_record.ticket_id:
            t = db.get(Ticket, failure_record.ticket_id)
            subject = t.assigned_agent_id if t else None
        if subject is None:
            return None  # no clean owner; do not penalize the logging tester
        trigger = ScoreTriggerType.test_failure
        key = "test_failure"
        label = "test failure"
    else:
        return None  # manual failure taxonomy: not auto-scored

    if subject is None:
        return None
    if scoring_svc.event_exists_for_ref(
        db, project_id=failure_record.project_id, subject_agent_id=subject,
        trigger_type=trigger, ref_type="failure_record", ref_id=failure_record.id,
    ):
        return None

    return scoring_svc.apply_score_event(
        db, project_id=failure_record.project_id, subject_agent_id=subject,
        sprint_id=failure_record.sprint_id, trigger_type=trigger,
        delta=points_for(key), source=ScoreSource.auto,
        reason=f"{label} on failure_record #{failure_record.id}",
        ref_type="failure_record", ref_id=failure_record.id, commit=commit,
    )


def score_stale(db: Session, ticket: Ticket, *, commit: bool = False):
    """Penalize a ticket that went stale (a stale alert was raised). Attributed
    to the assignee, idempotent per ticket. Returns the ScoreEvent or None."""
    agent_id = ticket.assigned_agent_id
    if not agent_id:
        return None
    if scoring_svc.event_exists_for_ref(
        db, project_id=ticket.project_id, subject_agent_id=agent_id,
        trigger_type=ScoreTriggerType.stale, ref_type="ticket", ref_id=ticket.id,
    ):
        return None
    return scoring_svc.apply_score_event(
        db, project_id=ticket.project_id, subject_agent_id=agent_id,
        sprint_id=ticket.sprint_id, trigger_type=ScoreTriggerType.stale,
        delta=points_for("stale"), source=ScoreSource.auto,
        reason=f"{ticket.ticket_key} went stale in_progress",
        ref_type="ticket", ref_id=ticket.id, commit=commit,
    )


def score_gate_miss(
    db: Session,
    sprint: Sprint,
    *,
    acting_agent_id: int | None = None,
    detail: str | None = None,
    commit: bool = False,
):
    """Penalize a blocked sprint close (a completion gate was unmet). Attributed
    to the agent who attempted the close (acting_agent_id), falling back to the
    project team-lead (the gate owner). One event per sprint, idempotent.

    Note: the sprint-close path raises and rolls back the request transaction,
    so the caller passes commit=True here to persist the penalty before the
    raise propagates. Returns the ScoreEvent or None.
    """
    subject = acting_agent_id or _project_tl_agent_id(db, sprint.project_id)
    if subject is None:
        return None
    if scoring_svc.event_exists_for_ref(
        db, project_id=sprint.project_id, subject_agent_id=subject,
        trigger_type=ScoreTriggerType.gate_miss, ref_type="sprint", ref_id=sprint.id,
    ):
        return None
    reason = "sprint close blocked by an unmet completion gate"
    if detail:
        reason = f"{reason}: {detail[:400]}"
    return scoring_svc.apply_score_event(
        db, project_id=sprint.project_id, subject_agent_id=subject,
        sprint_id=sprint.id, trigger_type=ScoreTriggerType.gate_miss,
        delta=points_for("gate_miss"), source=ScoreSource.auto,
        reason=reason, ref_type="sprint", ref_id=sprint.id, commit=commit,
    )
