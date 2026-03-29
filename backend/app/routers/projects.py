# Path: app/routers/projects.py
# File: projects.py
# Created: 2026-03-29
# Purpose: Project HTTP endpoints — CRUD, from-repo, gates, overhead, scan-tokens, docs, activity-feed
# Caller: app/main.py
# Callees: app/services/project.py, token_scan.py, models (Agent, Alert, ProjectAgent)
# Data In: HTTP requests
# Data Out: JSON responses (ProjectRead, gate status, scan results)
# Last Modified: 2026-03-29

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.activity_log import ActivityLog
from app.models.agent import Agent
from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.models.project import ProjectStatus
from app.models.project_agent import ProjectAgent
from app.schemas.project import ProjectCreate, ProjectOverheadIncrement, ProjectRead, ProjectUpdate
from app.schemas.test_result import TestResultRead
from app.services import project as svc
from app.services import test_result as test_svc
from app.services.token_scan import run_token_scan

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    status: ProjectStatus | None = Query(None),
    db: Session = Depends(get_db),
):
    return svc.list_projects(db, status=status)


class FromRepoRequest(BaseModel):
    repo_path: str


def _prefix_from_name(name: str) -> str:
    """Generate uppercase prefix (max 6 chars) from a project name."""
    # Split on hyphens, underscores, spaces
    words = re.split(r"[-_ ]+", name.strip())
    words = [w for w in words if w]
    if not words:
        return "PROJ"
    if len(words) == 1:
        return re.sub(r"[^A-Z0-9]", "", words[0].upper())[:6]
    # Use initials if multi-word
    initials = "".join(w[0] for w in words if w)
    return re.sub(r"[^A-Z0-9]", "", initials.upper())[:6]


def _scan_repo(repo: Path) -> dict:
    """Scan a repo directory for metadata to auto-populate a project."""
    name = repo.name
    description = None

    # Try package.json
    pkg_json = repo / "package.json"
    if pkg_json.is_file():
        try:
            pkg = json.loads(pkg_json.read_text())
            name = pkg.get("name", name)
            description = pkg.get("description")
        except (json.JSONDecodeError, OSError):
            pass

    # Try pyproject.toml (basic parsing — no toml dependency needed)
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file() and description is None:
        try:
            text = pyproject.read_text()
            for line in text.splitlines():
                if line.strip().startswith("name"):
                    m = re.search(r'name\s*=\s*"([^"]+)"', line)
                    if m:
                        name = m.group(1)
                if line.strip().startswith("description"):
                    m = re.search(r'description\s*=\s*"([^"]+)"', line)
                    if m:
                        description = m.group(1)
        except OSError:
            pass

    # Try README.md first line as description fallback
    readme = repo / "README.md"
    if readme.is_file() and description is None:
        try:
            first_lines = readme.read_text()[:500].splitlines()
            for line in first_lines:
                stripped = line.strip().lstrip("#").strip()
                if stripped and not stripped.startswith("!"):
                    description = stripped[:200]
                    break
        except OSError:
            pass

    if not description:
        description = "New project — needs setup"

    prefix = _prefix_from_name(name)
    # Clean name: replace hyphens/underscores with spaces, title case
    display_name = name.replace("-", " ").replace("_", " ").title()

    return {"prefix": prefix, "name": display_name, "description": description}


@router.post("/from-repo", response_model=ProjectRead, status_code=201)
def create_from_repo(data: FromRepoRequest, db: Session = Depends(get_db)):
    repo = Path(data.repo_path)
    if not repo.is_dir():
        raise HTTPException(400, f"Directory not found: {data.repo_path}")

    meta = _scan_repo(repo)

    # Ensure prefix is unique — append digits if needed
    base_prefix = meta["prefix"]
    prefix = base_prefix
    suffix = 2
    while db.scalar(select(svc.Project.id).where(svc.Project.prefix == prefix)):
        prefix = f"{base_prefix[:4]}{suffix}"
        suffix += 1

    create_data = ProjectCreate(
        prefix=prefix,
        name=meta["name"],
        description=meta["description"],
        repo_path=str(repo),
        force_initial_md=True,
        force_architecture_md=True,
    )
    project = svc.create_project(db, create_data)
    # Auto-check doc gates and raise alerts for missing docs
    _check_doc_gates(db, project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    return svc.create_project(db, data)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)
):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return svc.update_project(db, project, data)


@router.post("/{project_id}/overhead", response_model=ProjectRead)
def increment_project_overhead(
    project_id: int, data: ProjectOverheadIncrement, db: Session = Depends(get_db)
):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    # Normalize role: accept both "team_lead" and "team-lead"
    role = data.role.replace("-", "_") if data.role else data.role
    if role not in ("team_lead", "pm"):
        raise HTTPException(400, "role must be 'team_lead'/'team-lead' or 'pm'")
    return svc.increment_overhead(
        db, project, role, data.tokens_used, data.time_spent_seconds
    )


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    svc.delete_project(db, project)


_DOC_GATES = [
    ("force_initial_md", "INITIAL.md"),
    ("force_architecture_md", "ARCHITECTURE.md"),
]


def _check_doc_gates(db: Session, project) -> list[dict]:
    """Check doc gates and create deduplicated alerts for missing docs.

    Returns a list of gate status dicts.
    """
    gates = []
    for toggle_field, filename in _DOC_GATES:
        enabled = getattr(project, toggle_field)
        exists = None
        path = None
        if enabled and project.repo_path:
            path = str(Path(project.repo_path) / filename)
            exists = Path(path).is_file()

            if not exists:
                alert_title = f"{filename} required but not found at {path}. Sprint closure will be blocked."
                # Only create alert if one with the same title doesn't already exist for this project
                existing = db.scalar(
                    select(Alert.id)
                    .where(Alert.project_id == project.id)
                    .where(Alert.title == alert_title)
                    .where(Alert.status == AlertStatus.open)
                    .limit(1)
                )
                if not existing:
                    # Find TL agent for this project
                    tl_agent = db.scalars(
                        select(Agent.id)
                        .join(ProjectAgent, ProjectAgent.agent_id == Agent.id)
                        .where(ProjectAgent.project_id == project.id)
                        .where(Agent.role == "team-lead")
                        .limit(1)
                    ).first()
                    if tl_agent:
                        db.add(Alert(
                            project_id=project.id,
                            raised_by_agent_id=tl_agent,
                            title=alert_title,
                            body=f"The project toggle {toggle_field} is enabled but {filename} does not exist. Create this file before attempting to close a sprint.",
                            severity=AlertSeverity.critical,
                            status=AlertStatus.open,
                        ))
                        db.commit()

        gates.append({
            "toggle": toggle_field,
            "file": filename,
            "enabled": enabled,
            "exists": exists,
            "path": path,
            "passing": not enabled or exists is True,
        })

    return gates


@router.get("/{project_id}/gate-status")
def get_gate_status(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    gates = _check_doc_gates(db, project)

    return {
        "project_id": project_id,
        "all_passing": all(g["passing"] for g in gates),
        "gates": gates,
    }


@router.get("/{project_id}/tests", response_model=list[TestResultRead])
def list_project_tests(
    project_id: int,
    suite: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return test_svc.list_test_results(
        db, project_id=project_id, suite=suite, status=status, limit=limit
    )


@router.post("/{project_id}/scan-tokens")
def scan_project_tokens(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    try:
        result = run_token_scan(project_id)
    except Exception as exc:
        raise HTTPException(500, f"Token scan failed: {exc}")
    return result


_DOC_FILES = ["README.md", "QUICKSTART.md", "ARCHITECTURE.md", "INITIAL.md"]


@router.get("/{project_id}/docs")
def list_project_docs(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.repo_path:
        raise HTTPException(400, "Project has no repo_path configured")

    repo = Path(project.repo_path)
    docs = []
    for name in _DOC_FILES:
        filepath = repo / name
        exists = filepath.is_file()
        content = None
        if exists:
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception:
                content = None
        docs.append({
            "name": name,
            "path": str(filepath),
            "exists": exists,
            "content": content,
        })
    return docs


@router.get("/{project_id}/activity-feed")
def get_project_activity_feed(
    project_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    rows = db.execute(
        select(
            ActivityLog.id,
            ActivityLog.action,
            ActivityLog.entity_type,
            ActivityLog.entity_id,
            ActivityLog.details,
            ActivityLog.created_at,
            Agent.name.label("agent_name"),
        )
        .outerjoin(Agent, ActivityLog.agent_id == Agent.id)
        .where(ActivityLog.project_id == project_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    ).all()

    feed = []
    for row in rows:
        details = row.details
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, ValueError):
                pass
        feed.append({
            "id": row.id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "details": details,
            "agent_name": row.agent_name,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return feed
