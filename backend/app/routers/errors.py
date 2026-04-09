# Path: app/routers/errors.py
# File: errors.py
# Created: 2026-04-09
# Purpose: HTTP endpoints for error logging — POST from frontend/hooks, GET with filters
# Caller: app/main.py
# Callees: app/models/error_log.py
# Data In: HTTP requests
# Data Out: JSON responses (ErrorLogRead)
# Last Modified: 2026-04-09

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.error_log import ErrorLog, ErrorSource
from app.schemas.error_log import ErrorLogCreate, ErrorLogRead

router = APIRouter(prefix="/api/errors", tags=["errors"])


@router.post("", response_model=ErrorLogRead, status_code=201)
def create_error_log(data: ErrorLogCreate, db: Session = Depends(get_db)):
    source = ErrorSource.frontend
    if data.source in ("backend", "frontend", "hook"):
        source = ErrorSource(data.source)

    error = ErrorLog(
        project_id=data.project_id,
        agent_id=data.agent_id,
        source=source,
        endpoint=data.endpoint,
        error_type=data.error_type,
        message=data.message,
        stack_trace=data.stack_trace,
        file_path=data.file_path,
        function_name=data.function_name,
        line_number=data.line_number,
        status_code=data.status_code,
    )
    db.add(error)
    db.commit()
    db.refresh(error)
    return error


@router.get("", response_model=list[ErrorLogRead])
def list_error_logs(
    project_id: int | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(ErrorLog).order_by(ErrorLog.created_at.desc())
    if project_id is not None:
        stmt = stmt.where(ErrorLog.project_id == project_id)
    if source is not None and source in ("backend", "frontend", "hook"):
        stmt = stmt.where(ErrorLog.source == ErrorSource(source))
    stmt = stmt.limit(limit)
    return db.scalars(stmt).all()
