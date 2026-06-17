# Path: app/routers/projects.py
# File: projects.py
# Created: 2026-03-29
# Purpose: Project HTTP endpoints - CRUD, from-repo, gates, overhead, docs, activity-feed, token-budget, team, scaffold-agents (DWB-341), Jira table + sync (DWB-342)
# Caller: app/main.py
# Callees: app/services/project.py, app/services/project_agent.py, models (Agent, Alert, ProjectAgent)
# Data In: HTTP requests
# Data Out: JSON responses (ProjectRead, gate status, token budget, team listing)
# Last Modified: 2026-06-10

import json
import re
from datetime import datetime, timezone
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
from app.models.ticket import Ticket
from app.schemas.project import ProjectCreate, ProjectOverheadIncrement, ProjectRead, ProjectUpdate
from app.schemas.project_agent import ProjectTeamRead
from app.schemas.test_result import TestResultRead
from app.services import project as svc
from app.services import project_agent as pa_svc
from app.services import test_result as test_svc
from app.services.seed_demo import seed_demo_project

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


@router.post("/seed-demo", status_code=201)
def seed_demo(db: Session = Depends(get_db)):
    result = seed_demo_project(db)
    return result


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/{project_id}/team", response_model=ProjectTeamRead)
def get_project_team(
    project_id: int,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
):
    """DWB-313: single-roundtrip team listing for a project.

    Default returns only active agents. Pass ?include_inactive=true to get the
    full historical roster.
    """
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    agents = pa_svc.list_project_team(
        db, project_id=project_id, include_inactive=include_inactive
    )
    return {
        "project_id": project.id,
        "project_prefix": project.prefix,
        "agents": agents,
    }


@router.get("/{project_id}/jira-tickets")
def list_project_jira_tickets(
    project_id: int,
    q: str | None = Query(None, description="Fuzzy substring search across all 10 columns"),
    sort: str = Query("dwb_key", description="Column to sort by"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """DWB-342: unified Jira table for a project.

    Returns the 10-column row shape (DWB id/sprint/status + Jira
    id/sprint/status/assignee + created/updated + title) joined from the
    canonical tickets table and the jira_ticket_snapshots cache. Only
    tickets with a non-null jira_issue_key are returned (the table is
    for linked tickets only).

    Search is case-insensitive substring across every text column.
    Token-order-agnostic: splitting the query on whitespace requires
    EVERY token to appear somewhere in the row (matches the spec's
    "substring + token-order-agnostic" intent).

    404 when the project does not exist. Non-Jira projects (jira_base_url
    null) return 200 with an empty row list and a banner-friendly total=0
    so the UI can render the empty state without a separate API call.
    """
    from app.models.jira_ticket_snapshot import JiraTicketSnapshot
    from app.models.sprint import Sprint

    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Whitelist of sortable column keys -> SQL expression. Keeping the
    # mapping inline so an attacker can't pass a hostile ORDER BY string.
    sort_columns: dict[str, object] = {
        "dwb_key":          Ticket.ticket_key,
        "dwb_sprint":       Sprint.name,
        "dwb_status":       Ticket.status,
        "jira_key":         Ticket.jira_issue_key,
        "jira_sprint":      JiraTicketSnapshot.jira_sprint_name,
        "jira_status":      JiraTicketSnapshot.jira_status,
        "jira_assignee":    JiraTicketSnapshot.jira_assignee,
        # DWB-362: 11th column. Sortable like the others.
        "jira_issue_type":  JiraTicketSnapshot.jira_issue_type,
        # DWB-363: 12th column. Sort by epic key only - epic names are
        # free-form summaries and sorting by them is rarely useful.
        "jira_epic_key":    JiraTicketSnapshot.jira_epic_key,
        # DWB-364: 13th column. Subtask-only field; sort gathers
        # subtasks together on this column.
        "jira_parent_key":  JiraTicketSnapshot.jira_parent_key,
        "created_at":       Ticket.created_at,
        "updated_at":       Ticket.updated_at,
        "title":            Ticket.title,
    }
    sort_col = sort_columns.get(sort)
    if sort_col is None:
        raise HTTPException(400, f"unknown sort column '{sort}'")

    base = (
        select(Ticket, JiraTicketSnapshot, Sprint)
        .join(
            JiraTicketSnapshot,
            JiraTicketSnapshot.ticket_id == Ticket.id,
            isouter=True,
        )
        .join(Sprint, Sprint.id == Ticket.sprint_id, isouter=True)
        .where(Ticket.project_id == project_id)
        .where(Ticket.jira_issue_key.isnot(None))
    )

    # Fuzzy search: AND across whitespace-split tokens; each token must
    # match somewhere in any text field. Substring + case-insensitive.
    if q and q.strip():
        from sqlalchemy import or_
        searchable: list = [
            Ticket.ticket_key, Sprint.name, Ticket.title,
            Ticket.jira_issue_key,
            JiraTicketSnapshot.jira_sprint_name,
            JiraTicketSnapshot.jira_status,
            JiraTicketSnapshot.jira_assignee,
            JiraTicketSnapshot.jira_reporter,
            JiraTicketSnapshot.jira_title,
            # DWB-362: search hits issue_type too (e.g. typing "Bug"
            # filters to bug-type rows).
            JiraTicketSnapshot.jira_issue_type,
            # DWB-363: search hits both the epic key (e.g. "POR-5152")
            # and the resolved epic name ("Gemini AI Claims/Fraud").
            JiraTicketSnapshot.jira_epic_key,
            JiraTicketSnapshot.jira_epic_name,
            # DWB-364: search hits the subtask's parent key.
            JiraTicketSnapshot.jira_parent_key,
        ]
        for token in q.strip().split():
            like = f"%{token}%"
            base = base.where(or_(*(func.lower(col).like(like.lower()) for col in searchable)))

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    if order == "asc":
        base = base.order_by(sort_col.asc(), Ticket.id.asc())
    else:
        base = base.order_by(sort_col.desc(), Ticket.id.desc())
    base = base.limit(limit).offset(offset)

    rows = []
    for ticket, snapshot, sprint in db.execute(base).all():
        rows.append({
            "ticket_id": ticket.id,
            "dwb_key": ticket.ticket_key,
            "dwb_sprint": sprint.name if sprint else None,
            "dwb_status": ticket.status.value if hasattr(ticket.status, "value") else ticket.status,
            "title": ticket.title,
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
            "jira_key": ticket.jira_issue_key,
            "jira_sprint": snapshot.jira_sprint_name if snapshot else None,
            "jira_status": snapshot.jira_status if snapshot else None,
            "jira_assignee": snapshot.jira_assignee if snapshot else None,
            "jira_reporter": snapshot.jira_reporter if snapshot else None,
            "jira_title": snapshot.jira_title if snapshot else None,
            "jira_created_at": snapshot.jira_created_at if snapshot else None,
            "jira_updated_at": snapshot.jira_updated_at if snapshot else None,
            "last_synced_at": snapshot.last_synced_at if snapshot else None,
            # DWB-362: 11th column on every row. None on pre-DWB-362
            # snapshots; the UI null-guards with '-'.
            "jira_issue_type": snapshot.jira_issue_type if snapshot else None,
            # DWB-363: 12th column. UI renders KEY prominently + name as
            # tooltip; null-guards with '-' when both are None.
            "jira_epic_key":   snapshot.jira_epic_key   if snapshot else None,
            "jira_epic_name":  snapshot.jira_epic_name  if snapshot else None,
            # DWB-364: 13th column. Populated for subtasks only; non-
            # subtask rows serve None and the UI shows '-'.
            "jira_parent_key": snapshot.jira_parent_key if snapshot else None,
        })

    return {
        "project_id": project_id,
        "project_prefix": project.prefix,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "rows": rows,
    }


@router.post("/{project_id}/jira-sync", status_code=202)
def trigger_jira_sync(project_id: int, db: Session = Depends(get_db)):
    """DWB-342: manual Jira -> DWB sync (READ-ONLY ingestion).

    Synchronous in v1 - returns when the sync completes. The endpoint
    enforces single-sync concurrency via Project.last_jira_sync_status:
    a second concurrent caller gets 409.

    202 Accepted on success (the sync ran and the cache is fresh).
    400 when the project has no jira_base_url configured.
    404 when the project does not exist.
    409 when a sync is already in flight for this project.
    """
    from app.services import jira_sync as sync_svc

    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.jira_base_url:
        raise HTTPException(
            400,
            f"project '{project.prefix}' has no jira_base_url - configure Jira first",
        )

    try:
        sync_svc.run_sync(db, project_id)
    except sync_svc.SyncAlreadyRunning:
        raise HTTPException(409, f"a Jira sync is already running on project '{project.prefix}'")
    except sync_svc.SyncNotConfigured as exc:
        raise HTTPException(400, str(exc))

    # Re-read so the response carries the freshly-stamped sync row.
    db.refresh(project)
    return {
        "project_id": project_id,
        "status": project.last_jira_sync_status.value
            if hasattr(project.last_jira_sync_status, "value")
            else project.last_jira_sync_status,
        "started_at": project.last_jira_sync_at,
    }


@router.get("/{project_id}/jira-sync/status")
def get_jira_sync_status(project_id: int, db: Session = Depends(get_db)):
    """DWB-342: poll endpoint for the UI to detect sync completion.

    Returns the project-level sync flags. 404 when project missing.
    """
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return {
        "project_id": project_id,
        "status": project.last_jira_sync_status.value
            if hasattr(project.last_jira_sync_status, "value")
            else project.last_jira_sync_status,
        "last_synced_at": project.last_jira_sync_at,
        "counts": project.last_jira_sync_counts,
    }


@router.post("/{project_id}/scaffold-agents")
def scaffold_project_agents(project_id: int, db: Session = Depends(get_db)):
    """Walk every agent whose project_id matches and scaffold any missing
    memory dirs/files (DWB-341).

    Use case: project repo got cloned to a new machine or recreated from
    scratch; the agent rows still exist in DB but the on-disk dirs are
    gone. One call rehydrates the lot. Idempotent per agent - identity.md
    refreshes; scratchpad/lessons/recent_sessions are preserved when
    present, created empty when missing.

    Returns a per-agent disposition list (created/preserved/refreshed/
    skipped) so callers can see exactly what changed. Per-agent failures
    are recorded in the response rather than aborting the walk; one bad
    agent shouldn't block the rest of the team.

    404 if project missing. 400 if project.repo_path is null (no point
    walking - every per-agent call would skip).
    """
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.repo_path:
        raise HTTPException(
            400,
            f"project '{project.prefix}' has no repo_path - cannot scaffold "
            f"agent memory dirs (set project.repo_path first)",
        )

    from app.services import agent_memory  # local import avoids router-level cycle
    agents = list(
        db.scalars(
            select(Agent)
            .where(Agent.project_id == project_id)
            .order_by(Agent.name.asc())
        )
    )

    results = []
    for a in agents:
        try:
            res = agent_memory.scaffold_agent_dir(db, a.id)
            results.append({
                "agent_id": res.agent_id,
                "agent_name": a.name,
                "memory_dir": res.memory_dir,
                "created": res.created,
                "preserved": res.preserved,
                "refreshed": res.refreshed,
                "skipped": res.skipped,
                "skip_reason": res.skip_reason,
            })
        except agent_memory.ScaffoldError as e:
            results.append({
                "agent_id": a.id,
                "agent_name": a.name,
                "error": e.code,
                "detail": e.detail,
            })
    return {
        "project_id": project_id,
        "project_prefix": project.prefix,
        "agent_count": len(agents),
        "scaffolded": results,
    }


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


@router.post("/{project_id}/disable-jira")
def disable_jira(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    # Count affected tickets before clearing
    affected = db.query(Ticket).filter(
        Ticket.project_id == project_id,
        Ticket.jira_issue_key.isnot(None),
    ).count()
    # Clear jira_issue_key on all project tickets
    db.query(Ticket).filter(Ticket.project_id == project_id).update(
        {"jira_issue_key": None}, synchronize_session="fetch"
    )
    # Clear jira_project_key on the project
    project.jira_project_key = None
    db.commit()
    db.refresh(project)
    return {"project_id": project_id, "tickets_cleared": affected}


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    svc.delete_project(db, project)


_DOC_GATES = [
    ("force_initial_md", "INITIAL.md"),
    ("force_architecture_md", "ARCHITECTURE.md"),
    ("force_handoff_md", "HANDOFF.md"),
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


_DOC_FILES = ["README.md", "QUICKSTART.md", "ARCHITECTURE.md", "INITIAL.md", "HANDOFF.md"]


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
        last_modified = None
        if exists:
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception:
                content = None
            last_modified = datetime.fromtimestamp(
                filepath.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        docs.append({
            "name": name,
            "path": str(filepath),
            "exists": exists,
            "content": content,
            "last_modified": last_modified,
        })
    return docs


_PLAYBOOK_FILES = [
    "team_lead_playbook.md",
    "pm_playbook.md",
    "worker_playbook.md",
    "project_rules_team_lead.md",
    "project_rules_pm.md",
    "project_rules_worker.md",
]


@router.get("/{project_id}/playbook-files")
def list_project_playbook_files(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.repo_path:
        raise HTTPException(400, "Project has no repo_path configured")

    claude_dir = Path(project.repo_path) / ".claude"
    files = []
    for name in _PLAYBOOK_FILES:
        filepath = claude_dir / name
        exists = filepath.is_file()
        content = None
        last_modified = None
        if exists:
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception:
                content = None
            last_modified = datetime.fromtimestamp(
                filepath.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        files.append({
            "name": name,
            "path": str(filepath),
            "exists": exists,
            "content": content,
            "last_modified": last_modified,
        })
    return files


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
            Agent.role.label("agent_role"),
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
            "agent_role": row.agent_role,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return feed


# --- Token budget ---

# Post-DWB-331 rebalance (2026-06-05): after agent-def trim + playbook
# consolidation, the playbooks absorbed content (Identity flow, Memory Writes,
# stack details, Session Marker, etc.) and project_rules_worker absorbed the
# per-role stacks. Caps bumped so the canonical homes aren't starting in
# red/yellow on a clean repo:
#   playbook:       2500 → 4000  (PM at ~2860 was over; TL/worker at ~2440 warn)
#   project_rules:  1000 → 3000  (worker at ~2055 was over)
#   claude_md:      1500 → 2000  (was 93% warn)
#   architecture:   6000 → 7500  (was 91% warn)
#   readme:         2500 → 3500  (was 98% warn)
#   initial:        1500 → 2000  (was 91% warn)
# Unchanged: handoff (good headroom), memory_*, agent_def (stubs cap stays;
# 1500 is wasteful for 50-token stubs but flagged out of scope).
# Token ceilings, memory-file map, classifier, and estimator now live in
# app.config.token_budget (single source of truth shared with the
# consolidation gate and the memory-compaction gate). Aliased to the existing
# private names so the rest of this module is unchanged.
from app.config.token_budget import (  # noqa: E402
    MEMORY_FILES as _MEMORY_FILES,
    TOKEN_CEILINGS as _TOKEN_CEILINGS,
    classify_file as _classify_file,
    estimate_tokens as _estimate_tokens,
)

# Which files each role reads at startup (post-stub: playbooks are the real load)
_ROLE_FILES = {
    "team-lead": ["CLAUDE.md", "team_lead_playbook.md"],
    "pm": ["CLAUDE.md", "pm_playbook.md"],
    "frontend-worker": ["CLAUDE.md", "worker_playbook.md"],
    "backend-worker": ["CLAUDE.md", "worker_playbook.md"],
    "tester": ["CLAUDE.md", "worker_playbook.md"],
    "system-ops": ["CLAUDE.md", "worker_playbook.md"],
}


def compute_token_budget(db: Session, project) -> dict:
    """Build the token-budget payload for a project. Shared by the public
    endpoint and the consolidation-status endpoint. Caller is responsible for
    asserting project exists and has repo_path; raises ValueError otherwise.
    """
    if not project or not project.repo_path:
        raise ValueError("project has no repo_path")

    repo = Path(project.repo_path)
    files = []
    file_token_map: dict[str, int] = {}  # name -> tokens for startup calc

    # Root-level context files (CLAUDE/HANDOFF + per-project docs agents load at spawn)
    for name in [
        "CLAUDE.md",
        "HANDOFF.md",
        "ARCHITECTURE.md",
        "README.md",
        "INITIAL.md",
    ]:
        filepath = repo / name
        if filepath.is_file():
            try:
                text = filepath.read_text(encoding="utf-8")
            except Exception:
                text = ""
            tokens = _estimate_tokens(text)
            category = _classify_file(name)
            ceiling = _TOKEN_CEILINGS.get(category, 1000)
            ratio = tokens / ceiling if ceiling > 0 else 0
            status = "over" if ratio > 1.0 else "warning" if ratio > 0.8 else "ok"
            files.append({
                "path": str(filepath),
                "name": name,
                "category": category,
                "agent_name": None,
                "tokens": tokens,
                "ceiling": ceiling,
                "status": status,
            })
            file_token_map[name] = tokens

    # Agent definitions: .claude/agents/*.md
    agents_dir = repo / ".claude" / "agents"
    if agents_dir.is_dir():
        for filepath in sorted(agents_dir.glob("*.md")):
            if filepath.name.upper().endswith(".TEMPLATE"):
                continue
            try:
                text = filepath.read_text(encoding="utf-8")
            except Exception:
                text = ""
            tokens = _estimate_tokens(text)
            category = _classify_file(filepath.name)
            ceiling = _TOKEN_CEILINGS.get(category, 800)
            ratio = tokens / ceiling if ceiling > 0 else 0
            status = "over" if ratio > 1.0 else "warning" if ratio > 0.8 else "ok"
            files.append({
                "path": str(filepath),
                "name": f".claude/agents/{filepath.name}",
                "category": category,
                "agent_name": None,
                "tokens": tokens,
                "ceiling": ceiling,
                "status": status,
            })
            file_token_map[filepath.name] = tokens

    # Playbooks and project rules: .claude/*_playbook.md, .claude/project_rules_*.md
    claude_dir = repo / ".claude"
    if claude_dir.is_dir():
        for pattern in ["*_playbook.md", "project_rules_*.md"]:
            for filepath in sorted(claude_dir.glob(pattern)):
                try:
                    text = filepath.read_text(encoding="utf-8")
                except Exception:
                    text = ""
                tokens = _estimate_tokens(text)
                category = _classify_file(filepath.name)
                ceiling = _TOKEN_CEILINGS.get(category, 1000)
                ratio = tokens / ceiling if ceiling > 0 else 0
                status = (
                    "over" if ratio > 1.0 else "warning" if ratio > 0.8 else "ok"
                )
                files.append({
                    "path": str(filepath),
                    "name": f".claude/{filepath.name}",
                    "category": category,
                    "agent_name": None,
                    "tokens": tokens,
                    "ceiling": ceiling,
                    "status": status,
                })
                file_token_map[filepath.name] = tokens

    # Per-agent memory: .claude/agents/memory/{prefix}/{agent_name}/{file}
    # Counts every file each active agent on this project loads at spawn.
    if project.prefix:
        memory_root = repo / ".claude" / "agents" / "memory" / project.prefix
        active_agents = (
            db.query(Agent)
            .filter(Agent.project_id == project.id, Agent.is_active.is_(True))
            .order_by(Agent.name)
            .all()
        )
        for agent in active_agents:
            agent_mem_dir = memory_root / agent.name
            if not agent_mem_dir.is_dir():
                continue
            for fname, category in _MEMORY_FILES.items():
                filepath = agent_mem_dir / fname
                if not filepath.is_file():
                    continue
                try:
                    text = filepath.read_text(encoding="utf-8")
                except Exception:
                    text = ""
                tokens = _estimate_tokens(text)
                ceiling = _TOKEN_CEILINGS.get(category, 1000)
                ratio = tokens / ceiling if ceiling > 0 else 0
                status = (
                    "over" if ratio > 1.0 else "warning" if ratio > 0.8 else "ok"
                )
                files.append({
                    "path": str(filepath),
                    "name": f"memory/{agent.name}/{fname}",
                    "category": category,
                    "agent_name": agent.name,
                    "tokens": tokens,
                    "ceiling": ceiling,
                    "status": status,
                })

    total_tokens = sum(f["tokens"] for f in files)

    # Team startup cost: sum of files each role reads
    team_startup = 0
    for _role, role_files in _ROLE_FILES.items():
        for fname in role_files:
            team_startup += file_token_map.get(fname, 0)

    return {
        "files": files,
        "total_tokens": total_tokens,
        "team_startup_cost": team_startup,
    }


@router.get("/{project_id}/token-budget")
def get_token_budget(project_id: int, db: Session = Depends(get_db)):
    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.repo_path:
        raise HTTPException(400, "Project has no repo_path configured")
    return compute_token_budget(db, project)


@router.get("/{project_id}/consolidation-status")
def get_consolidation_status(
    project_id: int,
    sprint_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Per-agent consolidation gate status for a given sprint.

    Each active agent on the project gets a block with their ack state and the
    over-ceiling files they own (memory files + role-mapped repo files). The
    gate is satisfied when force_consolidation is off or every agent has acked.
    """
    from app.models.sprint import Sprint
    from app.services import agent_consolidation as consolidation_svc

    project = svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    sprint = db.get(Sprint, sprint_id)
    if not sprint or sprint.project_id != project_id:
        raise HTTPException(404, "Sprint not found for this project")
    return consolidation_svc.get_consolidation_status(db, project, sprint_id)
