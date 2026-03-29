import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.failure_record import FailureRecord
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.test_result import TestResult
from app.schemas.test_result import TestResultCreate


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

    for t in failed_tests:
        nodeid = t.get("nodeid", "unknown test")
        # Build notes from nodeid + error message
        message = t.get("message", "")
        notes = f"{nodeid}"
        if message:
            notes += f"\n{message[:500]}"

        db.add(FailureRecord(
            project_id=result.project_id,
            sprint_id=sprint_id,
            agent_id=tester_agent_id,
            logged_by_agent_id=tester_agent_id,
            failure_type="test_failure",
            severity="medium",
            attempt_number=1,
            notes=notes,
            resolved=False,
        ))

    db.commit()
