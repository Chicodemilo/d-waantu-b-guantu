# Path: app/schemas/failure_record.py
# File: failure_record.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for failure record CRUD
# Caller: app/routers/failure_records.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: FailureRecordCreate, FailureRecordUpdate, FailureRecordRead
# Last Modified: 2026-09-14 (DWB-510: reviewed flag)

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FailureRecordCreate(BaseModel):
    project_id: int
    ticket_id: int | None = None
    sprint_id: int
    agent_id: int
    logged_by_agent_id: int
    failure_type: str
    severity: str = "medium"
    attempt_number: int = 2
    notes: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    resolved: bool = False
    # DWB-510: a record may be created already-reviewed (e.g. a PM logging a
    # fully-analysed failure). Auto-created stubs leave this False.
    reviewed: bool = False


class FailureRecordUpdate(BaseModel):
    ticket_id: int | None = None
    failure_type: str | None = None
    severity: str | None = None
    attempt_number: int | None = None
    notes: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    resolved: bool | None = None
    # DWB-510: PM can set review state explicitly; when omitted, any edit via
    # the update service implicitly marks the record reviewed (a PM touching a
    # record IS the review), so a notes-only edit clears the gate.
    reviewed: bool | None = None


class FailureRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    ticket_id: int | None
    sprint_id: int
    agent_id: int
    logged_by_agent_id: int
    failure_type: str
    severity: str
    attempt_number: int
    notes: str | None
    root_cause: str | None
    resolution: str | None
    resolved: bool
    reviewed: bool
    created_at: datetime
    updated_at: datetime
