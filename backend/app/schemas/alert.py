from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.alert import AlertSeverity, AlertStatus


class AlertCreate(BaseModel):
    project_id: int
    raised_by_agent_id: int
    ticket_id: int | None = None
    title: str
    body: str
    severity: AlertSeverity = AlertSeverity.info


class DismissAllRequest(BaseModel):
    project_id: int | None = None


class DismissAllResponse(BaseModel):
    dismissed: int


class RunTestsRequest(BaseModel):
    project_id: int
    raised_by_agent_id: int | None = None


class AlertUpdate(BaseModel):
    status: AlertStatus | None = None
    resolved_at: datetime | None = None


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    raised_by_agent_id: int
    ticket_id: int | None
    title: str
    body: str
    severity: AlertSeverity
    status: AlertStatus
    created_at: datetime
    resolved_at: datetime | None
