# Path: app/routers/tracking.py
# File: tracking.py
# Created: 2026-03-30
# Purpose: Tracking HTTP endpoints — start/stop, token reports, overhead, summary
# Caller: app/main.py
# Callees: app/services/tracking.py
# Data In: HTTP requests
# Data Out: JSON responses (TrackingLog events, project summary)
# Last Modified: 2026-03-30

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ticket import Ticket
from app.models.project import Project
from app.services import tracking as svc

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


class StartStopRequest(BaseModel):
    ticket_id: int
    agent_id: int


class TokenReportRequest(BaseModel):
    ticket_id: int
    agent_id: int
    tokens: int
    source: str = "manual"


class OverheadRequest(BaseModel):
    project_id: int
    agent_id: int


@router.post("/start", status_code=201)
def track_start(data: StartStopRequest, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    entry = svc.log_start(db, data.ticket_id, data.agent_id)
    return {"id": entry.id, "event_type": entry.event_type, "timestamp": entry.timestamp.isoformat()}


@router.post("/stop", status_code=201)
def track_stop(data: StartStopRequest, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    entry = svc.log_stop(db, data.ticket_id, data.agent_id)
    return {"id": entry.id, "event_type": entry.event_type, "timestamp": entry.timestamp.isoformat()}


@router.post("/tokens", status_code=201)
def track_tokens(data: TokenReportRequest, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    entry = svc.log_tokens(db, data.ticket_id, data.agent_id, data.tokens, data.source)
    return {"id": entry.id, "event_type": entry.event_type, "tokens": entry.tokens, "timestamp": entry.timestamp.isoformat()}


@router.post("/overhead/start", status_code=201)
def track_overhead_start(data: OverheadRequest, db: Session = Depends(get_db)):
    project = db.get(Project, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    entry = svc.log_overhead_start(db, data.project_id, data.agent_id)
    return {"id": entry.id, "event_type": entry.event_type, "timestamp": entry.timestamp.isoformat()}


@router.post("/overhead/stop", status_code=201)
def track_overhead_stop(data: OverheadRequest, db: Session = Depends(get_db)):
    project = db.get(Project, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    entry = svc.log_overhead_stop(db, data.project_id, data.agent_id)
    return {"id": entry.id, "event_type": entry.event_type, "timestamp": entry.timestamp.isoformat()}


@router.get("/summary")
def get_tracking_summary(
    project_id: int = Query(...),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return svc.get_project_summary(db, project_id)
