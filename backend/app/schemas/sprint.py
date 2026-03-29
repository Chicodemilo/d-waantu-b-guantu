# Path: app/schemas/sprint.py
# File: sprint.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for sprint CRUD
# Caller: app/routers/sprints.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: SprintCreate, SprintUpdate, SprintRead
# Last Modified: 2026-03-29

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.sprint import SprintStatus


class SprintCreate(BaseModel):
    project_id: int
    epic_id: int | None = None  # auto-assigned if omitted
    name: str | None = None
    goal: str | None = None
    sprint_number: int
    status: SprintStatus = SprintStatus.planned
    start_date: date | None = None
    end_date: date | None = None


class SprintUpdate(BaseModel):
    epic_id: int | None = None
    name: str | None = None
    goal: str | None = None
    status: SprintStatus | None = None
    start_date: date | None = None
    end_date: date | None = None


class SprintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    epic_id: int
    name: str
    goal: str | None
    sprint_number: int
    status: SprintStatus
    start_date: date | None
    end_date: date | None
    created_at: datetime
    updated_at: datetime
