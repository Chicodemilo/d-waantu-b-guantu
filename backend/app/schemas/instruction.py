# Path: app/schemas/instruction.py
# File: instruction.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for instruction CRUD
# Caller: app/routers/instructions.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: InstructionCreate, InstructionUpdate, InstructionRead
# Last Modified: 2026-10-08 (DWB-651: request schemas refuse undeclared keys)

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.instruction import InstructionScope


class InstructionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # DWB-651

    scope: InstructionScope
    project_id: int | None = None
    agent_id: int | None = None
    title: str
    body: str


class InstructionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # DWB-651

    scope: InstructionScope | None = None
    project_id: int | None = None
    agent_id: int | None = None
    title: str | None = None
    body: str | None = None


class InstructionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: InstructionScope
    project_id: int | None
    agent_id: int | None
    title: str
    body: str
    created_at: datetime
    updated_at: datetime
