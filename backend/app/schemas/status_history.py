from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    old_status: str
    new_status: str
    changed_at: datetime
    changed_by_agent_id: int | None
