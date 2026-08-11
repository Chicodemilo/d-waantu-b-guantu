# Path: app/schemas/standards_audit.py
# File: standards_audit.py
# Created: 2026-08-11 (DWB-014)
# Purpose: Pydantic schemas for standards-audit create/read/list. Typed violation
#          and scorecard sub-models so a malformed audit payload 422s at the
#          boundary rather than landing garbage JSON in the DB.
# Caller: app/routers/standards_audits.py, app/services/standards_audit.py
# Callees: pydantic, app/models/standards_audit (AuditVerdict)
# Data In: JSON request body
# Data Out: StandardsAuditCreate, StandardsAuditRead, StandardsAuditListRead
# Last Modified: 2026-08-11 (DWB-014)

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.standards_audit import AuditVerdict


class Violation(BaseModel):
    """One standards violation found in the audited diff."""

    rule: str
    file: str | None = None
    line: int | None = None
    note: str | None = None
    severity: str | None = None


class ScorecardEntry(BaseModel):
    """One per-agent carrot/stick suggestion. DWB-016 consumes these to apply
    reputation deltas; recording an audit does NOT apply them."""

    agent: str
    delta: int
    reason: str | None = None


class StandardsAuditCreate(BaseModel):
    project_id: int
    sprint_id: int | None = None
    ticket_id: int | None = None
    pr_ref: str
    diff_range: str | None = None
    verdict: AuditVerdict
    violations: list[Violation] = []
    scorecard: list[ScorecardEntry] = []
    summary: str | None = None
    details: str | None = None
    run_at: datetime | None = None
    triggered_by: str = "manual"


class StandardsAuditListRead(BaseModel):
    """Slim schema for list responses - excludes `details` (raw diff can be
    multi-MB) to keep list payloads small. Violations + scorecard stay so a
    list view can show counts/summaries without a per-row detail fetch."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    sprint_id: int | None
    ticket_id: int | None
    pr_ref: str
    diff_range: str | None
    verdict: AuditVerdict
    violations: list | None
    scorecard: list | None
    summary: str | None
    run_at: datetime
    triggered_by: str
    created_at: datetime


class StandardsAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    sprint_id: int | None
    ticket_id: int | None
    pr_ref: str
    diff_range: str | None
    verdict: AuditVerdict
    violations: list | None
    scorecard: list | None
    summary: str | None
    details: str | None
    run_at: datetime
    triggered_by: str
    created_at: datetime
