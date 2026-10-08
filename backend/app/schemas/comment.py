# Path: app/schemas/comment.py
# File: comment.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for comment CRUD
# Caller: app/routers/comments.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: CommentCreate, CommentRead
# Last Modified: 2026-10-08 (DWB-651: request schemas refuse undeclared keys)

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # DWB-651

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
