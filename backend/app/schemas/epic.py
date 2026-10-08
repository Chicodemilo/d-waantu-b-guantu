# Path: app/schemas/epic.py
# File: epic.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for epic CRUD
# Caller: app/routers/epics.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: EpicCreate, EpicUpdate, EpicRead
# Last Modified: 2026-10-08 (DWB-651: request schemas refuse undeclared keys)

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.epic import EpicStatus


class EpicCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # DWB-651

    project_id: int
    name: str
    description: str | None = None
    status: EpicStatus = EpicStatus.open


class EpicUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # DWB-651

    name: str | None = None
    description: str | None = None
    status: EpicStatus | None = None


class EpicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: str | None
    status: EpicStatus
    created_at: datetime
    updated_at: datetime
