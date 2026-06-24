# Path: app/schemas/alert.py
# File: alert.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for alert CRUD
# Caller: app/routers/alerts.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: AlertCreate, AlertUpdate, AlertRead, SendToTeamResponse
# Last Modified: 2026-06-24 (DWB-462: category taxonomy)

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.alert import AlertCategory, AlertSeverity, AlertStatus


class AlertCreate(BaseModel):
    project_id: int
    raised_by_agent_id: int
    recipient_agent_id: int | None = None
    ticket_id: int | None = None
    title: str
    body: str
    severity: AlertSeverity = AlertSeverity.info
    # DWB-462: defaults to actionable when the caller doesn't specify.
    category: AlertCategory = AlertCategory.actionable


class DismissAllRequest(BaseModel):
    project_id: int | None = None


class DismissAllResponse(BaseModel):
    dismissed: int


class RunTestsRequest(BaseModel):
    project_id: int
    raised_by_agent_id: int | None = None


class RunTestsResponse(BaseModel):
    """DWB-463: a test-run request is recorded to the activity feed, not as an
    alert. Deliberately carries no `id`, so the activity-logger middleware does
    not also log a generic 'created' row for the POST."""
    status: str
    project_id: int
    action: str


class AlertUpdate(BaseModel):
    status: AlertStatus | None = None
    resolved_at: datetime | None = None


class SendToTeamResponse(BaseModel):
    file_written: str
    alerts_count: int


class AlertSlimRead(BaseModel):
    """Slim schema for ?fields=slim list responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    severity: AlertSeverity
    status: AlertStatus
    category: AlertCategory
    project_id: int


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    raised_by_agent_id: int
    recipient_agent_id: int | None
    ticket_id: int | None
    title: str
    body: str
    severity: AlertSeverity
    status: AlertStatus
    category: AlertCategory
    created_at: datetime
    resolved_at: datetime | None
    user_sent_at: datetime | None
