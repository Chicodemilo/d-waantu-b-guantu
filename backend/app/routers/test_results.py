# Path: app/routers/test_results.py
# File: test_results.py
# Created: 2026-03-29
# Purpose: Test result HTTP endpoints — list, get, create, performance
# Caller: app/main.py
# Callees: app/services/test_result.py, app/models/test_result.py
# Data In: HTTP requests
# Data Out: JSON responses (TestResultRead, performance list)
# Last Modified: 2026-03-29

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.test_result import TestResult
from app.schemas.test_result import TestResultCreate, TestResultListRead, TestResultRead
from app.services import test_result as svc

router = APIRouter(prefix="/api/test-results", tags=["test-results"])


@router.get("", response_model=list[TestResultListRead])
def list_test_results(
    project_id: int | None = Query(None),
    suite: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return svc.list_test_results(
        db, project_id=project_id, suite=suite, status=status, limit=limit
    )


@router.get("/performance")
def get_performance(
    project_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(
        TestResult.id,
        TestResult.run_at,
        TestResult.suite,
        TestResult.duration_seconds,
        TestResult.total_tests,
        TestResult.passed,
        TestResult.failed,
        TestResult.status,
    )
    if project_id:
        stmt = stmt.where(TestResult.project_id == project_id)
    stmt = stmt.order_by(TestResult.run_at.desc()).limit(limit)
    rows = db.execute(stmt).all()
    return [
        {
            "id": r.id,
            "run_at": r.run_at,
            "suite": r.suite,
            "duration_seconds": r.duration_seconds,
            "total_tests": r.total_tests,
            "passed": r.passed,
            "failed": r.failed,
            "status": r.status,
        }
        for r in rows
    ]


@router.get("/{result_id}", response_model=TestResultRead)
def get_test_result(result_id: int, db: Session = Depends(get_db)):
    result = svc.get_test_result(db, result_id)
    if not result:
        raise HTTPException(404, "Test result not found")
    return result


@router.post("", response_model=TestResultRead, status_code=201)
def create_test_result(data: TestResultCreate, db: Session = Depends(get_db)):
    return svc.create_test_result(db, data)
