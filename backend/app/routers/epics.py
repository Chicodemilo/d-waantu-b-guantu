from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.epic import EpicStatus
from app.schemas.epic import EpicCreate, EpicRead, EpicUpdate
from app.services import epic as svc

router = APIRouter(prefix="/api/epics", tags=["epics"])


@router.get("", response_model=list[EpicRead])
def list_epics(
    project_id: int | None = Query(None),
    status: EpicStatus | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_epics(db, project_id=project_id, status=status)


@router.get("/{epic_id}", response_model=EpicRead)
def get_epic(epic_id: int, db: Session = Depends(get_db)):
    epic = svc.get_epic(db, epic_id)
    if not epic:
        raise HTTPException(404, "Epic not found")
    return epic


@router.post("", response_model=EpicRead, status_code=201)
def create_epic(data: EpicCreate, db: Session = Depends(get_db)):
    return svc.create_epic(db, data)


@router.patch("/{epic_id}", response_model=EpicRead)
def update_epic(epic_id: int, data: EpicUpdate, db: Session = Depends(get_db)):
    epic = svc.get_epic(db, epic_id)
    if not epic:
        raise HTTPException(404, "Epic not found")
    return svc.update_epic(db, epic, data)


@router.delete("/{epic_id}", status_code=204)
def delete_epic(epic_id: int, db: Session = Depends(get_db)):
    epic = svc.get_epic(db, epic_id)
    if not epic:
        raise HTTPException(404, "Epic not found")
    svc.delete_epic(db, epic)
