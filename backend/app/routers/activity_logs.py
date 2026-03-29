from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.activity_log import ActivityLogCreate, ActivityLogRead
from app.services import activity_log as svc

router = APIRouter(prefix="/api/activity-logs", tags=["activity-logs"])


@router.get("", response_model=list[ActivityLogRead])
def list_activity_logs(
    project_id: int | None = Query(None),
    agent_id: int | None = Query(None),
    entity_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_activity_logs(
        db, project_id=project_id, agent_id=agent_id, entity_type=entity_type, limit=limit
    )


@router.get("/{log_id}", response_model=ActivityLogRead)
def get_activity_log(log_id: int, db: Session = Depends(get_db)):
    log = svc.get_activity_log(db, log_id)
    if not log:
        raise HTTPException(404, "Activity log not found")
    return log


@router.post("", response_model=ActivityLogRead, status_code=201)
def create_activity_log(data: ActivityLogCreate, db: Session = Depends(get_db)):
    return svc.create_activity_log(db, data)
