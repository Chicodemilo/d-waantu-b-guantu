# Path: app/services/activity_log.py
# File: activity_log.py
# Created: 2026-03-29
# Purpose: Activity log CRUD and filtered queries
# Caller: app/routers/activity_logs.py
# Callees: app/models/activity_log.py
# Data In: db: Session, filters
# Data Out: list[ActivityLog], ActivityLog
# Last Modified: 2026-03-29

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.schemas.activity_log import ActivityLogCreate


def list_activity_logs(
    db: Session,
    project_id: int | None = None,
    agent_id: int | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> list[ActivityLog]:
    stmt = select(ActivityLog)
    if project_id:
        stmt = stmt.where(ActivityLog.project_id == project_id)
    if agent_id:
        stmt = stmt.where(ActivityLog.agent_id == agent_id)
    if entity_type:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    stmt = stmt.order_by(ActivityLog.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_activity_log(db: Session, log_id: int) -> ActivityLog | None:
    return db.get(ActivityLog, log_id)


def create_activity_log(db: Session, data: ActivityLogCreate) -> ActivityLog:
    log = ActivityLog(**data.model_dump())
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
