# Path: app/schemas/activity_log.py
# File: activity_log.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for activity log CRUD
# Caller: app/routers/activity_logs.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: ActivityLogCreate, ActivityLogRead
# Last Modified: 2026-03-29

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ActivityLogCreate(BaseModel):
    project_id: int
    agent_id: int | None = None
    entity_type: str
    entity_id: int
    action: str
    details: str | None = None


class ActivityLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    agent_id: int | None
    entity_type: str
    entity_id: int
    action: str
    details: str | None
    created_at: datetime
