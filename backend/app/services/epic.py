from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.epic import Epic, EpicStatus
from app.schemas.epic import EpicCreate, EpicUpdate


def list_epics(
    db: Session,
    project_id: int | None = None,
    status: EpicStatus | None = None,
) -> list[Epic]:
    stmt = select(Epic)
    if project_id:
        stmt = stmt.where(Epic.project_id == project_id)
    if status:
        stmt = stmt.where(Epic.status == status)
    stmt = stmt.order_by(Epic.created_at.desc())
    return list(db.scalars(stmt).all())


def get_epic(db: Session, epic_id: int) -> Epic | None:
    return db.get(Epic, epic_id)


def create_epic(db: Session, data: EpicCreate) -> Epic:
    epic = Epic(**data.model_dump())
    db.add(epic)
    db.commit()
    db.refresh(epic)
    return epic


def update_epic(db: Session, epic: Epic, data: EpicUpdate) -> Epic:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(epic, key, value)
    db.commit()
    db.refresh(epic)
    return epic


def delete_epic(db: Session, epic: Epic) -> None:
    db.delete(epic)
    db.commit()
