# Path: app/routers/standards_audits.py
# File: standards_audits.py
# Created: 2026-08-11 (DWB-014)
# Purpose: Standards-audit HTTP endpoints - create a PR audit, list (filter by
#          project/sprint/ticket), get one. Thin router; logic lives in
#          app/services/standards_audit.py per the services doctrine.
# Caller: app/main.py
# Callees: app/services/standards_audit.py, app/schemas/standards_audit.py
# Data In: HTTP requests
# Data Out: JSON responses (StandardsAuditRead, StandardsAuditListRead)
# Last Modified: 2026-08-11 (DWB-014)

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.standards_audit import (
    StandardsAuditCreate,
    StandardsAuditListRead,
    StandardsAuditRead,
)
from app.services import standards_audit as svc

router = APIRouter(prefix="/api/standards-audits", tags=["standards-audits"])


@router.get("", response_model=list[StandardsAuditListRead])
def list_standards_audits(
    project_id: int | None = Query(None),
    sprint_id: int | None = Query(None),
    ticket_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_standards_audits(
        db,
        project_id=project_id,
        sprint_id=sprint_id,
        ticket_id=ticket_id,
        limit=limit,
    )


@router.get("/{audit_id}", response_model=StandardsAuditRead)
def get_standards_audit(audit_id: int, db: Session = Depends(get_db)):
    audit = svc.get_standards_audit(db, audit_id)
    if not audit:
        raise HTTPException(404, "Standards audit not found")
    return audit


@router.post("", response_model=StandardsAuditRead, status_code=201)
def create_standards_audit(data: StandardsAuditCreate, db: Session = Depends(get_db)):
    return svc.create_standards_audit(db, data)
