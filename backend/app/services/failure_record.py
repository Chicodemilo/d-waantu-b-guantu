# Path: app/services/failure_record.py
# File: failure_record.py
# Created: 2026-03-29
# Purpose: Failure record CRUD and filtered queries
# Caller: app/routers/failure_records.py
# Callees: app/models/failure_record.py
# Data In: db: Session, filters
# Data Out: list[FailureRecord], FailureRecord
# Last Modified: 2026-09-14 (DWB-510: PM edit marks record reviewed)

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.failure_record import FailureRecord
from app.schemas.failure_record import FailureRecordCreate, FailureRecordUpdate


def list_failure_records(
    db: Session,
    project_id: int | None = None,
    sprint_id: int | None = None,
    agent_id: int | None = None,
    failure_type: str | None = None,
    resolved: bool | None = None,
) -> list[FailureRecord]:
    stmt = select(FailureRecord)
    if project_id:
        stmt = stmt.where(FailureRecord.project_id == project_id)
    if sprint_id:
        stmt = stmt.where(FailureRecord.sprint_id == sprint_id)
    if agent_id:
        stmt = stmt.where(FailureRecord.agent_id == agent_id)
    if failure_type:
        stmt = stmt.where(FailureRecord.failure_type == failure_type)
    if resolved is not None:
        stmt = stmt.where(FailureRecord.resolved == resolved)
    stmt = stmt.order_by(FailureRecord.created_at.desc())
    return list(db.scalars(stmt).all())


def get_failure_record(db: Session, record_id: int) -> FailureRecord | None:
    return db.get(FailureRecord, record_id)


def create_failure_record(db: Session, data: FailureRecordCreate) -> FailureRecord:
    record = FailureRecord(**data.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_failure_record(
    db: Session, record: FailureRecord, data: FailureRecordUpdate
) -> FailureRecord:
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(record, key, value)
    # DWB-510: a PM editing a failure record IS the review. When the caller did
    # not set `reviewed` explicitly, mark it reviewed so the sprint-close gate
    # clears - structurally, not by matching boilerplate text in notes.
    if "reviewed" not in fields:
        record.reviewed = True
    db.commit()
    db.refresh(record)
    return record


def delete_failure_record(db: Session, record: FailureRecord) -> None:
    db.delete(record)
    db.commit()
