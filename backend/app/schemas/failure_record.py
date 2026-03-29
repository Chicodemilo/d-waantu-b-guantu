# Path: app/schemas/failure_record.py
# File: failure_record.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for failure record CRUD
# Caller: app/routers/failure_records.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: FailureRecordCreate, FailureRecordUpdate, FailureRecordRead
# Last Modified: 2026-03-29

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


class FailureRecordUpdate(BaseModel):
    ticket_id: int | None = None
    failure_type: str | None = None
    severity: str | None = None
    attempt_number: int | None = None
    notes: str | None = None
    root_cause: str | None = None
    resolution: str | None = None
    resolved: bool | None = None


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
    created_at: datetime
    updated_at: datetime
