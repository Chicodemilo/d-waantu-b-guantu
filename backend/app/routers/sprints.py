# Path: app/routers/sprints.py
# File: sprints.py
# Created: 2026-03-29
# Purpose: Sprint HTTP endpoints — CRUD with completion gate enforcement
# Caller: app/main.py
# Callees: app/services/sprint.py
# Data In: HTTP requests
# Data Out: JSON responses (SprintRead)
# Last Modified: 2026-03-29

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.sprint import SprintStatus
from app.schemas.sprint import SprintCreate, SprintRead, SprintUpdate
from app.services import sprint as svc

router = APIRouter(prefix="/api/sprints", tags=["sprints"])


@router.get("", response_model=list[SprintRead])
def list_sprints(
    project_id: int | None = Query(None),
    status: SprintStatus | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_sprints(db, project_id=project_id, status=status)


@router.get("/{sprint_id}", response_model=SprintRead)
def get_sprint(sprint_id: int, db: Session = Depends(get_db)):
    sprint = svc.get_sprint(db, sprint_id)
    if not sprint:
        raise HTTPException(404, "Sprint not found")
    return sprint


@router.post("", response_model=SprintRead, status_code=201)
def create_sprint(data: SprintCreate, db: Session = Depends(get_db)):
    return svc.create_sprint(db, data)


@router.patch("/{sprint_id}", response_model=SprintRead)
def update_sprint(
    sprint_id: int, data: SprintUpdate, db: Session = Depends(get_db)
):
    sprint = svc.get_sprint(db, sprint_id)
    if not sprint:
        raise HTTPException(404, "Sprint not found")
    return svc.update_sprint(db, sprint, data)


@router.delete("/{sprint_id}", status_code=204)
def delete_sprint(sprint_id: int, db: Session = Depends(get_db)):
    sprint = svc.get_sprint(db, sprint_id)
    if not sprint:
        raise HTTPException(404, "Sprint not found")
    svc.delete_sprint(db, sprint)
