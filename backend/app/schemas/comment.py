from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CommentCreate(BaseModel):
    ticket_id: int
    author_agent_id: int
    body: str


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author_agent_id: int
    body: str
    created_at: datetime
