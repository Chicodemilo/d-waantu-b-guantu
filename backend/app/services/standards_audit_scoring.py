# Path: app/services/standards_audit_scoring.py
# File: standards_audit_scoring.py
# Created: 2026-08-11 (DWB-016)
# Purpose: Apply a stored standards-audit scorecard (DWB-014) to the DWB-424
#          score_event ledger. Translates each {agent, delta, reason} scorecard
#          entry into one append-only score_event (source=audit), attributed to
#          the named agent. Idempotent per audit via ref_type/ref_id.
# Caller: app/routers/standards_audits.py (POST /{id}/apply-scorecard)
# Callees: app/services/scoring.py, app/models (standards_audit, score_event, agent)
# Data In: db: Session, StandardsAudit
# Data Out: ScorecardApplyResult
# Last Modified: 2026-08-11 (DWB-016)
#
# Design notes:
# - This is the APPLICATION layer. The auditor (upstream) already computed the
#   per-agent deltas + reasons and stored them on the audit's scorecard JSON
#   (worker sticks for violations on their tickets, an Archie stick when a repeat
#   violation survives review, a Pam carrot/stick per the ticketing signal). We
#   do not re-derive attribution here; we resolve each named agent and write the
#   ledger row with the audit's delta/reason. Keeping computation in the auditor
#   and application here matches the DWB-014 scorecard contract and Archie's
#   framing ("scorecard -> score_event application").
# - Explicit, not automatic: creating an audit does NOT score. A human/TL calls
#   the apply endpoint after reviewing the verdict (DWB-016 constraint 3), so the
#   human stays in the loop between verdict and reputation impact.
# - Anti-gaming caps: the peer per-action / per-target-per-sprint caps in
#   scoring.peer_score apply to source=peer ONLY. Audit application is
#   source=audit, so it intentionally bypasses those caps - exactly as the
#   auto-trigger engine (source=auto: ticket_closed, test_failure, ...) does. The
#   control on audit scoring is the auditor plus the explicit human-in-the-loop
#   apply step, not a per-action magnitude cap.
# - Idempotency: an audit is applied atomically once. If ANY non-reverted
#   score_event already references this audit (ref_type='standards_audit',
#   ref_id=audit.id), we short-circuit and write nothing, so re-POSTing apply
#   never double-writes.

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.score_event import ScoreEvent, ScoreSource, ScoreTriggerType
from app.models.standards_audit import StandardsAudit
from app.services import scoring

logger = logging.getLogger(__name__)

REF_TYPE = "standards_audit"


def _already_applied(db: Session, audit_id: int) -> bool:
    """True when a score_event already references this audit - the audit has been
    applied and must not be applied again (idempotency guard)."""
    existing = db.scalar(
        select(ScoreEvent.id)
        .where(ScoreEvent.ref_type == REF_TYPE)
        .where(ScoreEvent.ref_id == audit_id)
        .limit(1)
    )
    return existing is not None


def apply_scorecard(db: Session, audit: StandardsAudit) -> dict:
    """Apply ``audit``'s scorecard to the score_event ledger.

    Returns a summary dict:
      {
        "audit_id": int,
        "already_applied": bool,   # True -> nothing written (idempotent replay)
        "applied": [ {agent_id, agent_name, delta, trigger_type, event_id} ],
        "skipped": [ {agent, delta, reason} ],   # entries we could not apply
      }

    Each applied score_event carries source=audit, ref_type='standards_audit',
    ref_id=audit.id, and the audit's per-entry reason. The sprint is the audit's
    sprint_id when set, else the project's active sprint.
    """
    if _already_applied(db, audit.id):
        logger.info(
            "apply-scorecard: audit %s already applied - no-op (idempotent)",
            audit.id,
        )
        return {
            "audit_id": audit.id,
            "already_applied": True,
            "applied": [],
            "skipped": [],
        }

    sprint_id = audit.sprint_id or scoring.active_sprint_id(db, audit.project_id)
    scorecard = audit.scorecard or []

    applied: list[dict] = []
    skipped: list[dict] = []

    for entry in scorecard:
        agent_ref = entry.get("agent")
        delta = entry.get("delta")
        reason = entry.get("reason")

        if not agent_ref:
            skipped.append({"agent": agent_ref, "delta": delta, "reason": "no agent named"})
            continue
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            skipped.append({"agent": agent_ref, "delta": delta, "reason": "delta not an integer"})
            continue
        if delta == 0:
            skipped.append({"agent": agent_ref, "delta": 0, "reason": "zero delta (no-op)"})
            continue

        agent = scoring.resolve_agent_ref(db, agent_ref)
        if agent is None:
            skipped.append({"agent": agent_ref, "delta": delta, "reason": "agent not found"})
            continue
        if not scoring.is_project_member(db, agent.id, audit.project_id):
            skipped.append(
                {"agent": agent_ref, "delta": delta, "reason": "agent not on project roster"}
            )
            continue

        trigger = (
            ScoreTriggerType.audit_grant if delta > 0 else ScoreTriggerType.audit_demerit
        )
        event = scoring.apply_score_event(
            db,
            project_id=audit.project_id,
            subject_agent_id=agent.id,
            sprint_id=sprint_id,
            trigger_type=trigger,
            delta=delta,
            source=ScoreSource.audit,
            reason=reason,
            ref_type=REF_TYPE,
            ref_id=audit.id,
            commit=False,  # atomic batch: one commit for the whole scorecard
        )
        applied.append({
            "agent_id": agent.id,
            "agent_name": agent.name,
            "delta": delta,
            "trigger_type": trigger.value,
            "event_id": event.id,
        })

    db.commit()
    logger.info(
        "apply-scorecard: audit %s applied %d entries, skipped %d",
        audit.id, len(applied), len(skipped),
    )
    return {
        "audit_id": audit.id,
        "already_applied": False,
        "applied": applied,
        "skipped": skipped,
    }
