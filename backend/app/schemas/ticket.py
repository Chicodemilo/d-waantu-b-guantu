# Path: app/schemas/ticket.py
# File: ticket.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for ticket CRUD with token tracking
# Caller: app/routers/tickets.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: TicketCreate, TicketUpdate, TicketRead, TicketTokenIncrement, TicketTokenIncrementResult, StaleCheckInput, StaleCheckResponse
# Last Modified: 2026-09-14 (DWB-509: token increment requires tokens_used, forbids extras, echoes applied amount)

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
    # DWB-455: native sub-task parent link. Required when ticket_type=subtask,
    # must be null otherwise (enforced in the service layer with a 400). The
    # subtask inherits epic_id from its parent and defaults sprint_id to the
    # parent's sprint when sprint_id is omitted.
    parent_ticket_id: int | None = None
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
    # DWB-455: re-parent / convert to-or-from subtask. Same validation as
    # create runs on the resulting (ticket_type, parent_ticket_id) pair.
    parent_ticket_id: int | None = None
    tokens_used: int | None = None
    time_spent_seconds: int | None = None
    completed_at: datetime | None = None
    jira_issue_key: str | None = None


class TicketTokenIncrement(BaseModel):
    # DWB-509: tokens_used is REQUIRED (no default) and unknown keys are
    # forbidden, so a payload with a mistyped/absent key 422s instead of
    # silently binding 0 and returning 200 (a zero-effect call the sender
    # believes landed). Explicit tokens_used=0 remains valid: a time-only
    # report posts {tokens_used: 0, time_spent_seconds: N}.
    model_config = ConfigDict(extra="forbid")

    tokens_used: int
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
    # DWB-455: surfaced on the slim read so child summaries embedded in
    # TicketRead.subtasks carry their parent link.
    parent_ticket_id: int | None = None


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
    # DWB-455: self-referential sub-task linkage. parent_ticket_id is the FK;
    # subtasks embeds slim summaries of this ticket's direct children (always
    # empty for a subtask itself, since nesting is one level only).
    parent_ticket_id: int | None
    subtasks: list[TicketSlimRead] = []
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TicketTokenIncrementResult(TicketRead):
    """DWB-509: the token-increment response. Extends TicketRead (so every
    existing consumer that reads the ticket's cumulative fields still works)
    with an echo of the increment ACTUALLY applied by this call, making a
    zero-effect increment visible (applied_tokens == 0)."""
    applied_tokens: int
    applied_time_spent_seconds: int
