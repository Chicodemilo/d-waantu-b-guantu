from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectAgentCreate(BaseModel):
    project_id: int
    agent_id: int


class ProjectAgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    agent_id: int
    assigned_at: datetime
