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
