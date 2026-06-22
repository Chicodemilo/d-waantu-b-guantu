# Path: app/services/test_result.py
# File: test_result.py
# Created: 2026-03-29
# Purpose: Test result CRUD with auto-failure-record creation + auto-scoring of test failures (DWB-425)
# Caller: app/routers/test_results.py
# Callees: app/models (test_result, failure_record, agent, sprint), services/scoring_triggers
# Data In: db: Session, TestResultCreate
# Data Out: list[TestResult], TestResult
# Last Modified: 2026-06-22 (DWB-425)

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.failure_record import FailureRecord
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.test_result import TestResult
from app.schemas.test_result import TestResultCreate
from app.services import scoring_triggers


def list_test_results(
    db: Session,
    project_id: int | None = None,
    suite: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[TestResult]:
    stmt = select(TestResult)
    if project_id:
        stmt = stmt.where(TestResult.project_id == project_id)
    if suite:
        stmt = stmt.where(TestResult.suite == suite)
    if status:
        stmt = stmt.where(TestResult.status == status)
    stmt = stmt.order_by(TestResult.run_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_test_result(db: Session, result_id: int) -> TestResult | None:
    return db.get(TestResult, result_id)


def delete_test_result(db: Session, result_id: int) -> bool:
    """Delete a test_result row by id. Returns True on success, False if missing.

    DWB-310 — operator-driven orphan-row cleanup. Doesn't cascade to
    failure_records (those are independent diagnostic records); the row is
    removed in isolation.
    """
    result = db.get(TestResult, result_id)
    if result is None:
        return False
    db.delete(result)
    db.commit()
    return True


def create_test_result(db: Session, data: TestResultCreate) -> TestResult:
    result = TestResult(**data.model_dump(exclude_none=True))
    db.add(result)
    db.commit()
    db.refresh(result)

    # Auto-create failure_records for each failed test
    if result.status == "failed" and result.details:
        _create_failure_records_for_failed_tests(db, result)

    return result


def _create_failure_records_for_failed_tests(db: Session, result: TestResult) -> None:
    """Parse test details and create a failure_record for each failed test."""
    try:
        details = json.loads(result.details) if isinstance(result.details, str) else result.details
    except (json.JSONDecodeError, TypeError):
        return

    tests = details.get("tests", [])
    failed_tests = [t for t in tests if t.get("outcome") == "failed"]
    if not failed_tests:
        return

    # Find tester agent for this project
    tester_agent_id = db.scalars(
        select(Agent.id)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == result.project_id)
        .where(Agent.role == "tester")
        .limit(1)
    ).first()
    if not tester_agent_id:
        return

    # Use sprint from the test result, or find the active sprint
    sprint_id = result.sprint_id
    if not sprint_id:
        sprint_id = db.scalars(
            select(Sprint.id)
            .where(Sprint.project_id == result.project_id)
            .where(Sprint.status == SprintStatus.active)
            .order_by(Sprint.created_at.desc())
            .limit(1)
        ).first()
    if not sprint_id:
        return

    created: list[FailureRecord] = []
    for t in failed_tests:
        nodeid = t.get("nodeid", "unknown test")
        # Build notes from nodeid + error message
        message = t.get("message", "")
        notes = f"{nodeid}"
        if message:
            notes += f"\n{message[:500]}"

        fr = FailureRecord(
            project_id=result.project_id,
            sprint_id=sprint_id,
            agent_id=tester_agent_id,
            logged_by_agent_id=tester_agent_id,
            failure_type="test_failure",
            severity="medium",
            attempt_number=1,
            notes=notes,
            resolved=False,
        )
        db.add(fr)
        created.append(fr)

    db.flush()  # populate ids for the scoring refs

    # DWB-425: penalize test failures, attributed to the owning ticket's
    # assignee. These auto-records carry no ticket_id, so score_failure_record
    # currently skips them (it will not penalize the tester who logged them);
    # the call is wired so per-ticket test-failure records score correctly.
    # Side-effect only - never let scoring break test-result ingestion.
    try:
        for fr in created:
            scoring_triggers.score_failure_record(db, fr, commit=False)
    except Exception:
        pass

    db.commit()
