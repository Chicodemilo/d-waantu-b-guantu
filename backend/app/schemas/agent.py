from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    role: str
    api_key: str
    is_active: bool = True


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    role: str | None = None
    is_active: bool | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    role: str
    api_key: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
