from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.agent import Agent
from app.models.failure_record import FailureRecord
from app.models.sprint import Sprint
from app.schemas.failure_record import (
    FailureRecordCreate,
    FailureRecordRead,
    FailureRecordUpdate,
)
from app.services import failure_record as svc

router = APIRouter(prefix="/api/failure-records", tags=["failure-records"])


@router.get("", response_model=list[FailureRecordRead])
def list_failure_records(
    project_id: int | None = Query(None),
    sprint_id: int | None = Query(None),
    agent_id: int | None = Query(None),
    failure_type: str | None = Query(None),
    resolved: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_failure_records(
        db,
        project_id=project_id,
        sprint_id=sprint_id,
        agent_id=agent_id,
        failure_type=failure_type,
        resolved=resolved,
    )


@router.get("/summary")
def get_summary(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    # Total / resolved / open
    count_stmt = select(
        func.count().label("total"),
        func.sum(case((FailureRecord.resolved.is_(True), 1), else_=0)).label("resolved_count"),
        func.sum(case((FailureRecord.resolved.is_(False), 1), else_=0)).label("open_count"),
    ).select_from(FailureRecord)
    if project_id:
        count_stmt = count_stmt.where(FailureRecord.project_id == project_id)
    counts = db.execute(count_stmt).first()

    total = counts.total or 0
    resolved_count = int(counts.resolved_count or 0)
    open_count = int(counts.open_count or 0)

    # By type
    type_stmt = (
        select(FailureRecord.failure_type, func.count().label("count"))
        .group_by(FailureRecord.failure_type)
        .order_by(func.count().desc())
    )
    if project_id:
        type_stmt = type_stmt.where(FailureRecord.project_id == project_id)
    by_type = [{"failure_type": r[0], "count": r[1]} for r in db.execute(type_stmt).all()]

    # By agent
    agent_stmt = (
        select(FailureRecord.agent_id, Agent.name, func.count().label("count"))
        .join(Agent, FailureRecord.agent_id == Agent.id)
        .group_by(FailureRecord.agent_id, Agent.name)
        .order_by(func.count().desc())
    )
    if project_id:
        agent_stmt = agent_stmt.where(FailureRecord.project_id == project_id)
    by_agent = [
        {"agent_id": r[0], "agent_name": r[1], "count": r[2]}
        for r in db.execute(agent_stmt).all()
    ]

    # By sprint
    sprint_stmt = (
        select(FailureRecord.sprint_id, Sprint.name, func.count().label("count"))
        .join(Sprint, FailureRecord.sprint_id == Sprint.id)
        .group_by(FailureRecord.sprint_id, Sprint.name)
        .order_by(func.count().desc())
    )
    if project_id:
        sprint_stmt = sprint_stmt.where(FailureRecord.project_id == project_id)
    by_sprint = [
        {"sprint_id": r[0], "sprint_name": r[1], "count": r[2]}
        for r in db.execute(sprint_stmt).all()
    ]

    # Trend (by date)
    trend_stmt = (
        select(
            func.date(FailureRecord.created_at).label("date"),
            func.count().label("count"),
        )
        .group_by(func.date(FailureRecord.created_at))
        .order_by(func.date(FailureRecord.created_at))
    )
    if project_id:
        trend_stmt = trend_stmt.where(FailureRecord.project_id == project_id)
    trend = [
        {"date": str(r[0]), "count": r[1]}
        for r in db.execute(trend_stmt).all()
    ]

    return {
        "total": total,
        "resolved_count": resolved_count,
        "open_count": open_count,
        "by_type": by_type,
        "by_agent": by_agent,
        "by_sprint": by_sprint,
        "trend": trend,
    }


@router.get("/{record_id}", response_model=FailureRecordRead)
def get_failure_record(record_id: int, db: Session = Depends(get_db)):
    record = svc.get_failure_record(db, record_id)
    if not record:
        raise HTTPException(404, "Failure record not found")
    return record


@router.post("", response_model=FailureRecordRead, status_code=201)
def create_failure_record(data: FailureRecordCreate, db: Session = Depends(get_db)):
    return svc.create_failure_record(db, data)


@router.patch("/{record_id}", response_model=FailureRecordRead)
def update_failure_record(
    record_id: int, data: FailureRecordUpdate, db: Session = Depends(get_db)
):
    record = svc.get_failure_record(db, record_id)
    if not record:
        raise HTTPException(404, "Failure record not found")
    return svc.update_failure_record(db, record, data)


@router.delete("/{record_id}", status_code=204)
def delete_failure_record(record_id: int, db: Session = Depends(get_db)):
    record = svc.get_failure_record(db, record_id)
    if not record:
        raise HTTPException(404, "Failure record not found")
    svc.delete_failure_record(db, record)
