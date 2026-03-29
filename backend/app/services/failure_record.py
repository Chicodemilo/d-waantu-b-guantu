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
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)
    return record


def delete_failure_record(db: Session, record: FailureRecord) -> None:
    db.delete(record)
    db.commit()
