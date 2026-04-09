# Path: app/services/sprint.py
# File: sprint.py
# Created: 2026-03-29
# Purpose: Sprint CRUD, completion gates, and post-close automation
# Caller: app/routers/sprints.py
# Callees: models (sprint, ticket, alert, agent, failure_record, test_result)
# Data In: db: Session, SprintCreate/Update
# Data Out: list[Sprint], Sprint
# Last Modified: 2026-03-29

import logging
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.epic import Epic, EpicStatus
from app.models.failure_record import FailureRecord
from app.models.project import Project
from app.models.project_agent import ProjectAgent
from app.models.sprint import Sprint, SprintStatus
from app.models.test_result import TestResult
from app.models.ticket import Ticket, TicketStatus, TicketType
from app.schemas.sprint import SprintCreate, SprintUpdate

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
logger = logging.getLogger(__name__)

# Matches generic names like "DWB Sprint 4", "INGEST Sprint 1", "Sprint 3"
_GENERIC_NAME_RE = re.compile(r"^([A-Z]+ )?Sprint \d+$", re.IGNORECASE)


def _generate_name_from_goal(goal: str) -> str:
    """Generate a descriptive sprint name from the goal text, max ~50 chars."""
    name = goal.strip()
    if len(name) > 50:
        # Cut at word boundary
        name = name[:50].rsplit(" ", 1)[0]
    return name.title()


def list_sprints(
    db: Session,
    project_id: int | None = None,
    status: SprintStatus | None = None,
) -> list[Sprint]:
    stmt = select(Sprint)
    if project_id:
        stmt = stmt.where(Sprint.project_id == project_id)
    if status:
        stmt = stmt.where(Sprint.status == status)
    stmt = stmt.order_by(Sprint.created_at.desc())
    return list(db.scalars(stmt).all())


def get_sprint(db: Session, sprint_id: int) -> Sprint | None:
    return db.get(Sprint, sprint_id)


def create_sprint(db: Session, data: SprintCreate) -> Sprint:
    values = data.model_dump()

    # Validate project exists
    project = db.get(Project, values["project_id"])
    if not project:
        raise HTTPException(404, "Project not found")

    # Auto-assign epic_id if not provided
    if values.get("epic_id") is None:
        epic = db.scalars(
            select(Epic)
            .where(Epic.project_id == values["project_id"])
            .where(Epic.status.in_([EpicStatus.in_progress, EpicStatus.open]))
            .order_by(Epic.created_at.desc())
            .limit(1)
        ).first()
        if not epic:
            raise HTTPException(400, "No open or in-progress epic found for this project. Create an epic first or provide epic_id.")
        values["epic_id"] = epic.id
    else:
        # Validate the provided epic exists
        epic = db.get(Epic, values["epic_id"])
        if not epic:
            raise HTTPException(404, "Epic not found")

    name = values.get("name") or ""
    goal = values.get("goal") or ""
    # Auto-generate name if empty/null or generic, and goal is available
    if goal and (not name.strip() or _GENERIC_NAME_RE.match(name.strip())):
        values["name"] = _generate_name_from_goal(goal)
    elif not name.strip():
        values["name"] = f"Sprint {values.get('sprint_number', '?')}"
    sprint = Sprint(**values)
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    return sprint


def update_sprint(db: Session, sprint: Sprint, data: SprintUpdate) -> Sprint:
    old_status = sprint.status
    updates = data.model_dump(exclude_unset=True)

    transitioning_to_completed = (
        updates.get("status") == SprintStatus.completed
        and old_status != SprintStatus.completed
    )

    # Validate completion gates before applying changes
    if transitioning_to_completed:
        _check_completion_gates(db, sprint)

    for key, value in updates.items():
        setattr(sprint, key, value)
    db.commit()
    db.refresh(sprint)

    if transitioning_to_completed:
        _on_sprint_completed(db, sprint)

    return sprint


def _check_completion_gates(db: Session, sprint: Sprint) -> None:
    """Validate project-level gates before allowing sprint completion."""
    project = db.get(Project, sprint.project_id)
    if not project:
        return

    if project.force_test_run:
        # Require at least one test run for this project during the sprint
        stmt = select(func.count()).select_from(TestResult).where(
            TestResult.project_id == project.id
        )
        if sprint.start_date:
            stmt = stmt.where(TestResult.run_at >= sprint.start_date)
        count = db.scalar(stmt) or 0
        if count == 0:
            raise HTTPException(
                400,
                "Cannot complete sprint: force_test_run is enabled but no test runs "
                f"found for project '{project.prefix}'"
                + (f" since sprint start ({sprint.start_date})" if sprint.start_date else "")
                + ". Run tests before closing the sprint.",
            )

    if project.force_test_coverage:
        uncovered = _get_uncovered_routers()
        if uncovered:
            raise HTTPException(
                400,
                "Cannot complete sprint: force_test_coverage is enabled but these "
                f"routers have no test files: {', '.join(uncovered)}",
            )

    # Documentation gates — check file existence at project repo_path
    if project.repo_path:
        for toggle, filename in [
            (project.force_initial_md, "INITIAL.md"),
            (project.force_architecture_md, "ARCHITECTURE.md"),
        ]:
            if toggle:
                path = Path(project.repo_path) / filename
                if not path.is_file():
                    raise HTTPException(
                        400,
                        f"Cannot complete sprint: {filename} not found at {path}",
                    )

    # Unreviewed failure records gate — block if stubs exist for sprint tickets
    sprint_ticket_ids = list(db.scalars(
        select(Ticket.id).where(Ticket.sprint_id == sprint.id)
    ).all())
    if sprint_ticket_ids:
        unreviewed = list(db.execute(
            select(FailureRecord.id, Ticket.ticket_key)
            .join(Ticket, FailureRecord.ticket_id == Ticket.id)
            .where(FailureRecord.ticket_id.in_(sprint_ticket_ids))
            .where(
                (FailureRecord.failure_type == "TBD")
                | (
                    (FailureRecord.failure_type == "rework")
                    & (FailureRecord.notes.like("%Auto-detected%"))
                )
            )
        ).all())
        if unreviewed:
            keys = sorted({r.ticket_key for r in unreviewed})
            raise HTTPException(
                400,
                f"Cannot complete sprint: unreviewed failure records on tickets: "
                f"{', '.join(keys)}. PM must review and update failure_type/notes before closing.",
            )


def _get_uncovered_routers() -> list[str]:
    """Return list of router filenames that have no corresponding test file."""
    routers_dir = BACKEND_DIR / "app" / "routers"
    tests_dir = BACKEND_DIR / "tests"
    test_files = {f.name for f in tests_dir.glob("test_*.py")}
    uncovered = []
    for f in sorted(routers_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        expected = f"test_{f.name}"
        if expected not in test_files:
            uncovered.append(f.name)
    return uncovered


_ALERT_ROLES = ("team-lead", "pm", "tester")


def _find_agent_by_role(db: Session, project_id: int, role: str) -> Agent | None:
    """Find an agent assigned to a project by role."""
    return db.scalars(
        select(Agent)
        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
        .where(ProjectAgent.project_id == project_id)
        .where(Agent.role == role)
        .limit(1)
    ).first()


def _on_sprint_completed(db: Session, sprint: Sprint) -> None:
    alert_title = f"Sprint {sprint.name} closed — tests needed"
    alert_body = (
        f"Sprint S{sprint.sprint_number} ({sprint.name}) has been completed. "
        "Tests should be written for all new features."
    )

    tester_agent = None
    for role in _ALERT_ROLES:
        agent = _find_agent_by_role(db, sprint.project_id, role)
        if not agent:
            continue
        if role == "tester":
            tester_agent = agent
        db.add(Alert(
            project_id=sprint.project_id,
            raised_by_agent_id=agent.id,
            title=alert_title,
            body=alert_body,
            severity=AlertSeverity.info,
            status=AlertStatus.open,
        ))

    # Find the next active sprint for the same project
    next_sprint = db.scalars(
        select(Sprint)
        .where(Sprint.project_id == sprint.project_id)
        .where(Sprint.status == SprintStatus.active)
        .order_by(Sprint.created_at.asc())
        .limit(1)
    ).first()

    if next_sprint and tester_agent:
        # Auto-generate next ticket number for the project
        max_num = db.scalar(
            select(func.coalesce(func.max(Ticket.ticket_number), 0))
            .where(Ticket.project_id == sprint.project_id)
        )
        next_num = max_num + 1
        project = db.get(Project, sprint.project_id)
        ticket_key = f"{project.prefix}-{next_num:03d}"

        db.add(Ticket(
            project_id=sprint.project_id,
            sprint_id=next_sprint.id,
            epic_id=next_sprint.epic_id,
            assigned_agent_id=tester_agent.id,
            ticket_number=next_num,
            ticket_key=ticket_key,
            title=f"Write tests for S{sprint.sprint_number}: {sprint.name}",
            ticket_type=TicketType.task,
            status=TicketStatus.todo,
        ))

    db.commit()

    # Token attribution is handled in real-time by Claude Code lifecycle hooks.


def delete_sprint(db: Session, sprint: Sprint) -> None:
    db.delete(sprint)
    db.commit()
