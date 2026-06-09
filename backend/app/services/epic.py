# Path: app/services/epic.py
# File: epic.py
# Created: 2026-03-29
# Purpose: Epic CRUD with single-in_progress-per-project enforcement (DWB-331)
# Caller: app/routers/epics.py
# Callees: app/models/epic.py
# Data In: db: Session, EpicCreate/Update
# Data Out: list[Epic], Epic
# Last Modified: 2026-06-09

from fastapi import HTTPException
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


def _find_in_progress_epic(
    db: Session, project_id: int, exclude_id: int | None = None
) -> Epic | None:
    """Return the existing in_progress epic for a project, or None.

    `exclude_id` lets the PATCH path skip the row being updated so a
    no-op transition (already in_progress) doesn't false-trip.
    """
    stmt = (
        select(Epic)
        .where(Epic.project_id == project_id)
        .where(Epic.status == EpicStatus.in_progress)
    )
    if exclude_id is not None:
        stmt = stmt.where(Epic.id != exclude_id)
    return db.scalars(stmt).first()


def _raise_conflict_if_in_progress_exists(
    db: Session, project_id: int, exclude_id: int | None = None
) -> None:
    """409 if another epic on the same project is already in_progress.

    The DB-level (project_id, is_in_progress) UNIQUE index enforces this
    too, but the service-layer check produces a friendly error body with
    the offending epic's id + name instead of an opaque IntegrityError.
    """
    existing = _find_in_progress_epic(db, project_id, exclude_id=exclude_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "another_in_progress_epic",
                "message": (
                    f"Project {project_id} already has an in_progress epic "
                    f"(id={existing.id}, name={existing.name!r}). Close it "
                    f"before starting another."
                ),
                "active_epic_id": existing.id,
                "active_epic_name": existing.name,
            },
        )


def create_epic(db: Session, data: EpicCreate) -> Epic:
    if data.status == EpicStatus.in_progress:
        _raise_conflict_if_in_progress_exists(db, data.project_id)
    epic = Epic(**data.model_dump())
    db.add(epic)
    db.commit()
    db.refresh(epic)
    return epic


def update_epic(db: Session, epic: Epic, data: EpicUpdate) -> Epic:
    updates = data.model_dump(exclude_unset=True)
    if (
        "status" in updates
        and updates["status"] == EpicStatus.in_progress
        and epic.status != EpicStatus.in_progress
    ):
        _raise_conflict_if_in_progress_exists(
            db, epic.project_id, exclude_id=epic.id
        )
    for key, value in updates.items():
        setattr(epic, key, value)
    db.commit()
    db.refresh(epic)
    return epic


def delete_epic(db: Session, epic: Epic) -> None:
    db.delete(epic)
    db.commit()
