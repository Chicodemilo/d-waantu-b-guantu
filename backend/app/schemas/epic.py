from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.epic import EpicStatus


class EpicCreate(BaseModel):
    project_id: int
    name: str
    description: str | None = None
    status: EpicStatus = EpicStatus.open


class EpicUpdate(BaseModel):
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
