# Path: app/services/standards_audit.py
# File: standards_audit.py
# Created: 2026-08-11 (DWB-014)
# Purpose: StandardsAudit CRUD - create/list/get for recorded PR standards
#          audits. Validates parent FKs (project required, sprint/ticket optional)
#          so a bad reference returns a clean 4xx instead of an IntegrityError
#          500. Recording an audit does NOT apply its scorecard (that is DWB-016).
# Caller: app/routers/standards_audits.py
# Callees: app/models (standards_audit, project, sprint, ticket)
# Data In: db: Session, StandardsAuditCreate
# Data Out: list[StandardsAudit], StandardsAudit
# Last Modified: 2026-08-11 (DWB-014)

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.sprint import Sprint
from app.models.standards_audit import StandardsAudit
from app.models.ticket import Ticket
from app.schemas.standards_audit import StandardsAuditCreate


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
    db.commit()
    db.refresh(audit)
    return audit
