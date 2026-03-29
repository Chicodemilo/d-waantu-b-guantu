# Path: app/schemas/ticket.py
# File: ticket.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for ticket CRUD with token tracking
# Caller: app/routers/tickets.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: TicketCreate, TicketUpdate, TicketRead, TicketTokenIncrement
# Last Modified: 2026-03-29

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.ticket import TicketStatus, TicketType


class TicketCreate(BaseModel):
    project_id: int
    epic_id: int | None = None
    sprint_id: int | None = None  # auto-assigned if omitted
    assigned_agent_id: int | None = None
    ticket_number: int
    ticket_key: str
    title: str
    description: str | None = None
    ticket_type: TicketType = TicketType.task
    status: TicketStatus = TicketStatus.backlog


class TicketUpdate(BaseModel):
    epic_id: int | None = None
    sprint_id: int | None = None
    assigned_agent_id: int | None = None
    title: str | None = None
    description: str | None = None
    ticket_type: TicketType | None = None
    status: TicketStatus | None = None
    tokens_used: int | None = None
    time_spent_seconds: int | None = None
    completed_at: datetime | None = None


class TicketTokenIncrement(BaseModel):
    tokens_used: int = 0
    time_spent_seconds: int = 0
    source: str | None = None


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    epic_id: int | None
    sprint_id: int
    assigned_agent_id: int | None
    ticket_number: int
    ticket_key: str
    title: str
    description: str | None
    ticket_type: TicketType
    status: TicketStatus
    tokens_used: int
    time_spent_seconds: int
    token_source: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
