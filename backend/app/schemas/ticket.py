# Path: app/schemas/ticket.py
# File: ticket.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for ticket CRUD with token tracking
# Caller: app/routers/tickets.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: TicketCreate, TicketUpdate, TicketRead, TicketTokenIncrement, StaleCheckInput, StaleCheckResponse
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
    # DWB-332: surfaced on create so the Jira-disabled gate (project-level
    # project.jira_base_url null) can refuse linking attempts at the POST
    # path too. Service-layer rejects with a clean 400 when the project is
    # not Jira-linked.
    jira_issue_key: str | None = None


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
    jira_issue_key: str | None = None


class TicketTokenIncrement(BaseModel):
    tokens_used: int = 0
    time_spent_seconds: int = 0
    source: str | None = None


class StaleCheckInput(BaseModel):
    ticket_id: int
    project_id: int
    minutes_stale: int
    agent_name: str


class StaleCheckResponse(BaseModel):
    alert_created: bool
    alert_id: int | None = None


class TicketSlimRead(BaseModel):
    """Slim schema for ?fields=slim list responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_key: str
    title: str
    status: TicketStatus
    sprint_id: int
    project_id: int
    assigned_agent_id: int | None
    ticket_type: TicketType


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
    jira_issue_key: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
