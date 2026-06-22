# Path: app/services/sprint.py
# File: sprint.py
# Created: 2026-03-29
# Purpose: Sprint CRUD, completion gates (incl. doc + consolidation), post-close automation, semantic activity events (DWB-410)
# Caller: app/routers/sprints.py
# Callees: models (sprint, ticket, alert, agent, failure_record, test_result, project), agent_consolidation svc, git, services/activity_log
# Data In: db: Session, SprintCreate/Update, acting_agent_id
# Data Out: list[Sprint], Sprint
# Last Modified: 2026-06-19 (DWB-410)

import logging
import re
import subprocess
from datetime import date
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
from app.services.activity_log import log_activity


def _sprint_event_details(sprint: Sprint) -> dict:
    """details payload shared by sprint_opened / sprint_closed events (DWB-410)."""
    details: dict = {"sprint_number": sprint.sprint_number}
    if sprint.goal:
        details["goal"] = sprint.goal
    return details


def _emit_sprint_event(
    db: Session, sprint: Sprint, action: str, acting_agent_id: int | None
) -> None:
    """Emit a semantic sprint activity event and commit it (DWB-410)."""
    log_activity(
        db, sprint.project_id, acting_agent_id, "sprint", sprint.id, action,
        _sprint_event_details(sprint),
    )
    db.commit()

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


def _find_active_sprint(
    db: Session, project_id: int, exclude_id: int | None = None
) -> Sprint | None:
    """Return the existing active sprint for a project, or None."""
    stmt = (
        select(Sprint)
        .where(Sprint.project_id == project_id)
        .where(Sprint.status == SprintStatus.active)
    )
    if exclude_id is not None:
        stmt = stmt.where(Sprint.id != exclude_id)
    return db.scalars(stmt).first()


def _raise_conflict_if_active_exists(
    db: Session, project_id: int, exclude_id: int | None = None
) -> None:
    """409 if another sprint on the same project is already active (DWB-331).

    The DB-level (project_id, is_active) UNIQUE index enforces this too,
    but the service-layer pre-check produces a friendly 409 body with
    the offending sprint's id + name instead of an opaque IntegrityError.
    """
    existing = _find_active_sprint(db, project_id, exclude_id=exclude_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "another_active_sprint",
                "message": (
                    f"Project {project_id} already has an active sprint "
                    f"(id={existing.id}, name={existing.name!r}, "
                    f"number={existing.sprint_number}). Close it before "
                    f"starting another."
                ),
                "active_sprint_id": existing.id,
                "active_sprint_name": existing.name,
                "active_sprint_number": existing.sprint_number,
            },
        )


def create_sprint(db: Session, data: SprintCreate, acting_agent_id: int | None = None) -> Sprint:
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

    # DWB-331: refuse a second active sprint per project at the service
    # layer so callers see a friendly 409 (not an IntegrityError from
    # the DB-level UNIQUE index).
    if values.get("status") == SprintStatus.active:
        _raise_conflict_if_active_exists(db, values["project_id"])

    sprint = Sprint(**values)
    db.add(sprint)
    db.commit()
    db.refresh(sprint)

    # DWB-410: a sprint created directly into `active` is opened on creation.
    if sprint.status == SprintStatus.active:
        _emit_sprint_event(db, sprint, "sprint_opened", acting_agent_id)

    return sprint


def update_sprint(
    db: Session, sprint: Sprint, data: SprintUpdate, acting_agent_id: int | None = None
) -> Sprint:
    old_status = sprint.status
    updates = data.model_dump(exclude_unset=True)

    transitioning_to_completed = (
        updates.get("status") == SprintStatus.completed
        and old_status != SprintStatus.completed
    )
    transitioning_to_active = (
        updates.get("status") == SprintStatus.active
        and old_status != SprintStatus.active
    )

    # Validate completion gates before applying changes
    if transitioning_to_completed:
        _check_completion_gates(db, sprint)
    # DWB-331: refuse a second active sprint per project on PATCH transitions
    # too (e.g. flipping planned -> active when another active sprint exists).
    if transitioning_to_active:
        _raise_conflict_if_active_exists(
            db, sprint.project_id, exclude_id=sprint.id
        )

    for key, value in updates.items():
        setattr(sprint, key, value)
    db.commit()
    db.refresh(sprint)

    if transitioning_to_completed:
        _on_sprint_completed(db, sprint)

    # DWB-410: semantic open/close events on top of the middleware's generic
    # `updated` row (distinct verbs per the no-double-log rule).
    if transitioning_to_active:
        _emit_sprint_event(db, sprint, "sprint_opened", acting_agent_id)
    if transitioning_to_completed:
        _emit_sprint_event(db, sprint, "sprint_closed", acting_agent_id)

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
            (project.force_handoff_md, "HANDOFF.md"),
        ]:
            if toggle:
                path = Path(project.repo_path) / filename
                if not path.is_file():
                    raise HTTPException(
                        400,
                        f"Cannot complete sprint: {filename} not found at {path}",
                    )

    # Code-header gate (DWB-403) — opt-in via force_headers, default OFF. When
    # enabled, block close if any .py file touched during the sprint is missing
    # the mandatory code-header block. Scope is sprint-touched files only, never
    # repo-wide legacy. No scan, no token cost when the toggle is off.
    if project.force_headers:
        missing_headers = sprint_touched_py_files_missing_header(
            project.repo_path, sprint.start_date
        )
        if missing_headers:
            raise HTTPException(
                400,
                "Cannot complete sprint: force_headers is enabled but these "
                "sprint-touched .py files are missing the code-header block: "
                f"{', '.join(missing_headers)}",
            )

    # Consolidation gate — every active agent who participated in the sprint
    # must have an ack row when force_consolidation is enabled (DWB-326).
    if project.force_consolidation:
        from app.services import agent_consolidation as consolidation_svc
        unacked = consolidation_svc.unacked_agents_for_sprint(db, sprint)
        # Denominator = active participants (the set we actually require acks
        # from), not all active agents on the project. Pre-DWB-326 this was
        # all active agents, which made the M/N display misleading when the
        # active roster was larger than the sprint team.
        participant_ids = consolidation_svc.participants_for_sprint(db, sprint)
        total_required = db.scalar(
            select(func.count()).select_from(Agent)
            .where(
                Agent.project_id == project.id,
                Agent.is_active.is_(True),
                Agent.id.in_(participant_ids) if participant_ids else Agent.id.is_(None),
            )
        ) or 0
        if unacked:
            raise HTTPException(
                400,
                f"consolidation gate failed: {len(unacked)} of {total_required} "
                f"agents have not acked ({', '.join(a.name for a in unacked)})",
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


# DWB-403: code-header gate. The header marker is the canonical first-block
# fields from .claude/rules/global/code-header-format.md. A touched .py file
# must carry both to count as headered; empty files (no code) are exempt.
_HEADER_MARKERS = ("# Path:", "# Purpose:")


def _git_lines(repo_path: str, args: list[str]) -> list[str]:
    """Run a git command in repo_path and return non-empty stdout lines.

    Any failure (not a git repo, git missing, timeout) returns [] so the gate
    degrades to "nothing to scan" rather than blocking a close on tooling.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def sprint_touched_py_files_missing_header(
    repo_path: str | None, start_date: "date | None"
) -> list[str]:
    """Return repo-relative .py files touched in the sprint that lack a header.

    "Touched in the sprint" = the union of (a) files added/modified/renamed in
    commits since ``start_date`` and (b) currently staged, unstaged, and
    untracked .py changes (in-flight work not yet committed). Scope is .py only:
    project_rules mandates the header block on Python source; other languages
    have no defined header convention here. Repo-wide legacy files are NOT
    scanned, only sprint-touched ones. Empty files are exempt (no code).

    Returns a sorted list of relative paths missing the header marker. A
    non-git or unreadable repo yields [] (the gate passes rather than blocking
    a close on tooling).
    """
    if not repo_path:
        return []
    repo = Path(repo_path)
    if not repo.is_dir():
        return []

    rels: set[str] = set()
    if start_date is not None:
        rels.update(_git_lines(repo_path, [
            "log", f"--since={start_date.isoformat()}",
            "--diff-filter=AMR", "--name-only", "--pretty=format:", "--", "*.py",
        ]))
    rels.update(_git_lines(repo_path, [
        "diff", "--cached", "--name-only", "--diff-filter=AMR", "--", "*.py",
    ]))
    rels.update(_git_lines(repo_path, [
        "diff", "--name-only", "--diff-filter=AMR", "--", "*.py",
    ]))
    rels.update(_git_lines(repo_path, [
        "ls-files", "--others", "--exclude-standard", "--", "*.py",
    ]))

    missing: list[str] = []
    for rel in rels:
        if not rel.endswith(".py"):
            continue
        fpath = repo / rel
        if not fpath.is_file():
            continue  # deleted/renamed-away path still listed by git
        try:
            text = fpath.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue  # empty file: no code, no header required
        if not all(marker in text for marker in _HEADER_MARKERS):
            missing.append(rel)
    return sorted(missing)


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

    # Find the next sprint for the same project. Post-DWB-331 only one
    # sprint can be active per project, so the auto-ticket target is the
    # next planned (queued) sprint. We also accept active as a fallback
    # for any legacy data ordering oddities; the OR keeps the lookup
    # robust without depending on the order pre-completion ran.
    next_sprint = db.scalars(
        select(Sprint)
        .where(Sprint.project_id == sprint.project_id)
        .where(Sprint.id != sprint.id)
        .where(
            Sprint.status.in_([SprintStatus.planned, SprintStatus.active])
        )
        .order_by(Sprint.sprint_number.asc(), Sprint.created_at.asc())
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
