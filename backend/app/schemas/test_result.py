# Path: app/schemas/test_result.py
# File: test_result.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for test result CRUD
# Caller: app/routers/test_results.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: TestResultCreate, TestResultRead
# Last Modified: 2026-03-29

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TestResultCreate(BaseModel):
    project_id: int
    sprint_id: int | None = None
    ticket_id: int | None = None
    run_at: datetime | None = None
    suite: str
    total_tests: int
    passed: int
    failed: int
    skipped: int = 0
    duration_seconds: float = 0.0
    status: str
    details: str | None = None
    triggered_by: str = "manual"
    triggered_context: str | None = None


class TestResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    sprint_id: int | None
    ticket_id: int | None
    run_at: datetime
    suite: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    status: str
    details: str | None
    triggered_by: str
    triggered_context: str | None
    created_at: datetime
