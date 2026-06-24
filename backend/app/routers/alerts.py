# Path: app/routers/alerts.py
# File: alerts.py
# Created: 2026-03-29
# Purpose: Alert HTTP endpoints — CRUD, dismiss-all, send-to-team, run-tests
# Caller: app/main.py
# Callees: app/services/alert.py
# Data In: HTTP requests
# Data Out: JSON responses (AlertRead)
# Last Modified: 2026-03-29

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.alert import AlertCategory, AlertSeverity, AlertStatus
from app.schemas.alert import AlertCreate, AlertRead, AlertSlimRead, AlertUpdate, DismissAllRequest, DismissAllResponse, RunTestsRequest, RunTestsResponse, SendToTeamResponse
from app.services import alert as svc
from app.services import project as project_svc
from app.services.activity_log import log_activity

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    project_id: int | None = Query(None),
    severity: AlertSeverity | None = Query(None),
    status: AlertStatus | None = Query(None),
    category: AlertCategory | None = Query(None),
    fields: str | None = Query(None),
    db: Session = Depends(get_db),
):
    alerts = svc.list_alerts(
        db, project_id=project_id, severity=severity, status=status, category=category
    )
    schema = AlertSlimRead if fields == "slim" else AlertRead
    return [schema.model_validate(a) for a in alerts]


@router.post("/send-to-team", response_model=SendToTeamResponse)
def send_to_team(project_id: int = Query(...), db: Session = Depends(get_db)):
    """Write open alerts to .claude/ALERTS_PENDING.md in the project repo."""
    project = project_svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.repo_path:
        raise HTTPException(400, "Project has no repo_path configured")
    return svc.send_to_team(db, project)


@router.post("/dismiss-all", response_model=DismissAllResponse)
def dismiss_all_alerts(data: DismissAllRequest, db: Session = Depends(get_db)):
    count = svc.dismiss_all(db, project_id=data.project_id)
    return DismissAllResponse(dismissed=count)


@router.post("/run-tests", response_model=RunTestsResponse, status_code=201)
def request_test_run(data: RunTestsRequest, db: Session = Depends(get_db)):
    """DWB-463: an ad-hoc test-run request is an action, not an alert. It is
    recorded to the project activity feed (test_run_requested) instead of
    creating an Alert row."""
    project = project_svc.get_project(db, data.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    log_activity(
        db,
        data.project_id,
        data.raised_by_agent_id,
        "project",
        data.project_id,
        "test_run_requested",
        {"message": f"Ad-hoc test run requested for project {project.name}"},
    )
    db.commit()
    return RunTestsResponse(
        status="recorded", project_id=data.project_id, action="test_run_requested"
    )


@router.get("/{alert_id}", response_model=AlertRead)
def get_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = svc.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    return alert


@router.post("", response_model=AlertRead, status_code=201)
def create_alert(data: AlertCreate, db: Session = Depends(get_db)):
    return svc.create_alert(db, data)


@router.patch("/{alert_id}", response_model=AlertRead)
def update_alert(
    alert_id: int, data: AlertUpdate, db: Session = Depends(get_db)
):
    alert = svc.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    return svc.update_alert(db, alert, data)
