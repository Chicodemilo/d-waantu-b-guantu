# Path: app/services/standards_audit.py
# File: standards_audit.py
# Created: 2026-08-11 (DWB-014)
# Purpose: StandardsAudit CRUD - create/list/get for recorded PR standards
#          audits. Validates parent FKs (project required, sprint/ticket optional)
#          so a bad reference returns a clean 4xx instead of an IntegrityError
#          500. Recording an audit does NOT apply its scorecard (that is DWB-016).
#          Also owns the force_standards_audit gate-status computation (DWB-017)
#          so the router stays thin (logic in services, per our standards).
#          DWB-028: raises a visible Alert on every audit create + attributes the
#          audit to the fixed The_Auditor agent in the activity feed.
# Caller: app/routers/standards_audits.py, app/routers/projects.py (gate-status)
# Callees: app/models (standards_audit, project, sprint, ticket, agent, alert, project_agent), services/activity_log, config.settings
# Data In: db: Session, StandardsAuditCreate
# Data Out: list[StandardsAudit], StandardsAudit, audit-gate state dict
# Last Modified: 2026-08-12 (DWB-028: audit visibility - alert + auditor attribution)

import logging

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent import Agent
from app.models.alert import Alert, AlertCategory, AlertSeverity, AlertStatus
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.standards_audit import AuditVerdict, StandardsAudit
from app.models.ticket import Ticket
from app.schemas.standards_audit import StandardsAuditCreate
from app.services.activity_log import log_activity

logger = logging.getLogger(__name__)

# DWB-028: the fixed system agent audit writes attribute to. Created by the
# DWB-028 data migration; resolved by name when STANDARDS_AUDIT_AGENT_ID is unset.
AUDITOR_AGENT_NAME = "The_Auditor"


def list_standards_audits(
    db: Session,
    project_id: int | None = None,
    sprint_id: int | None = None,
    ticket_id: int | None = None,
    limit: int = 50,
) -> list[StandardsAudit]:
    stmt = select(StandardsAudit)
    if project_id:
        stmt = stmt.where(StandardsAudit.project_id == project_id)
    if sprint_id:
        stmt = stmt.where(StandardsAudit.sprint_id == sprint_id)
    if ticket_id:
        stmt = stmt.where(StandardsAudit.ticket_id == ticket_id)
    stmt = stmt.order_by(StandardsAudit.run_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_standards_audit(db: Session, audit_id: int) -> StandardsAudit | None:
    return db.get(StandardsAudit, audit_id)


def create_standards_audit(db: Session, data: StandardsAuditCreate) -> StandardsAudit:
    """Create a standards_audit row. Validates parent FKs up front so a missing
    project/sprint/ticket is a 404, not a DB IntegrityError 500."""
    if db.get(Project, data.project_id) is None:
        raise HTTPException(404, "Project not found")
    if data.sprint_id is not None and db.get(Sprint, data.sprint_id) is None:
        raise HTTPException(404, "Sprint not found")
    if data.ticket_id is not None and db.get(Ticket, data.ticket_id) is None:
        raise HTTPException(404, "Ticket not found")

    audit = StandardsAudit(
        project_id=data.project_id,
        sprint_id=data.sprint_id,
        ticket_id=data.ticket_id,
        pr_ref=data.pr_ref,
        diff_range=data.diff_range,
        verdict=data.verdict,
        # Store the sub-models as plain JSON-able dicts.
        violations=[v.model_dump() for v in data.violations],
        scorecard=[s.model_dump() for s in data.scorecard],
        summary=data.summary,
        details=data.details,
        triggered_by=data.triggered_by,
    )
    if data.run_at is not None:
        audit.run_at = data.run_at

    db.add(audit)
    db.flush()  # populate audit.id for the alert + activity attribution

    # DWB-028: make the audit visible. Attribute to the fixed auditor agent and
    # raise an alert (info on pass / warning on reject). Best-effort - never let
    # visibility wiring fail the audit write.
    auditor_id = resolve_auditor_agent_id(db)
    _raise_audit_alert(db, audit, auditor_id)
    if auditor_id is not None:
        log_activity(
            db,
            audit.project_id,
            auditor_id,
            "standards_audit",
            audit.id,
            "standards_audit_recorded",
            {
                "verdict": audit.verdict.value,
                "violations": len(audit.violations or []),
                "pr_ref": audit.pr_ref,
            },
        )

    db.commit()
    db.refresh(audit)
    return audit


def resolve_auditor_agent_id(db: Session) -> int | None:
    """Resolve the agent audit writes attribute to (DWB-028).

    Prefers the configured STANDARDS_AUDIT_AGENT_ID when set and the agent
    exists; otherwise falls back to the fixed ``The_Auditor`` agent by name
    (created by the DWB-028 data migration). None when neither resolves - the
    caller degrades gracefully (alert skipped, no attribution) rather than
    failing the audit write.
    """
    configured = settings.STANDARDS_AUDIT_AGENT_ID
    if configured is not None and db.get(Agent, configured) is not None:
        return configured
    agent = db.scalar(select(Agent).where(Agent.name == AUDITOR_AGENT_NAME))
    return agent.id if agent else None


def _fallback_alert_raiser(db: Session, project_id: int) -> int | None:
    """When no auditor agent resolves, use the project's TL (else any roster
    agent) as the alert's raised_by. None when the project has no agents - the
    alert is then skipped (raised_by is NOT NULL)."""
    tl = db.scalar(
        select(Agent.id)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
        .where(Agent.role == "team-lead")
        .limit(1)
    )
    if tl:
        return tl
    return db.scalar(
        select(ProjectAgent.agent_id)
        .where(ProjectAgent.project_id == project_id)
        .limit(1)
    )


def _raise_audit_alert(db: Session, audit: StandardsAudit, auditor_id: int | None) -> None:
    """DWB-028: raise a visible Alert for a recorded audit - info on pass,
    warning on reject. Title carries the audit id, verdict, linked ticket key,
    and violation count. Best-effort: if no agent can be the raiser, skip rather
    than fail the create (raised_by_agent_id is NOT NULL)."""
    raised_by = auditor_id or _fallback_alert_raiser(db, audit.project_id)
    if raised_by is None:
        logger.warning(
            "standards audit %s: no agent to attribute the alert to; skipping alert",
            audit.id,
        )
        return

    n = len(audit.violations or [])
    plural = "s" if n != 1 else ""
    ticket_key = audit.ticket.ticket_key if audit.ticket is not None else None
    verdict = audit.verdict.value.upper()

    title_parts = [f"Standards audit #{audit.id}: {verdict}"]
    if ticket_key:
        title_parts.append(ticket_key)
    title_parts.append(f"{n} violation{plural}")
    title = " - ".join(title_parts)

    body = (
        f"Standards audit #{audit.id} recorded for {audit.pr_ref}: verdict "
        f"{verdict}, {n} violation{plural}."
        + (f" Ticket {ticket_key}." if ticket_key else "")
    )

    is_pass = audit.verdict == AuditVerdict.passed
    db.add(Alert(
        project_id=audit.project_id,
        raised_by_agent_id=raised_by,
        recipient_agent_id=None,  # project-wide, no specific recipient
        ticket_id=audit.ticket_id,
        title=title,
        body=body,
        severity=AlertSeverity.info if is_pass else AlertSeverity.warning,
        status=AlertStatus.open,
        category=AlertCategory.actionable,
    ))
    db.flush()


def audit_gate_status(db: Session, project) -> dict:
    """Compute the force_standards_audit gate state for the gate-status endpoint
    (DWB-017).

    When the toggle is on, the gate passes only if a PASSING standards audit
    exists for the project dated at/after the active sprint's start (the same
    "since sprint start" window force_test_run uses). Reject-only or no audit ->
    blocked. No query happens when the toggle is off.

    COMPLEMENTS force_coding_standards_md: the file gate asserts the standards
    doc exists; this gate asserts the code actually conforms. Keep both.

    Returns the gate dict the router appends verbatim to the gate-status payload:
    {kind, toggle, enabled, passing, latest_audit_verdict}. Kept here (not in the
    router) so the gate's DB access + logic live in a service, matching where the
    sprint-close half of this gate already lives (services/sprint.py).
    """
    enabled = bool(project.force_standards_audit)
    has_passing = False
    latest_audit_verdict = None

    if enabled:
        active = db.scalars(
            select(Sprint)
            .where(Sprint.project_id == project.id)
            .where(Sprint.status == SprintStatus.active)
            .order_by(Sprint.id.desc())
            .limit(1)
        ).first()
        start_date = active.start_date if active else None

        # Latest audit verdict (any date) surfaced as a UI detail.
        latest = db.scalars(
            select(StandardsAudit)
            .where(StandardsAudit.project_id == project.id)
            .order_by(StandardsAudit.created_at.desc(), StandardsAudit.id.desc())
            .limit(1)
        ).first()
        latest_audit_verdict = latest.verdict.value if latest else None

        stmt = select(func.count()).select_from(StandardsAudit).where(
            StandardsAudit.project_id == project.id,
            StandardsAudit.verdict == AuditVerdict.passed,
        )
        if start_date:
            stmt = stmt.where(StandardsAudit.created_at >= start_date)
        has_passing = (db.scalar(stmt) or 0) > 0

    return {
        "kind": "audit",
        "toggle": "force_standards_audit",
        "enabled": enabled,
        "passing": not enabled or has_passing,
        "latest_audit_verdict": latest_audit_verdict,
    }
