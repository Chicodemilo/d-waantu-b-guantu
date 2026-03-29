# Path: app/schemas/agent.py
# File: agent.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for agent CRUD
# Caller: app/routers/agents.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: AgentCreate, AgentUpdate, AgentRead
# Last Modified: 2026-03-29

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
