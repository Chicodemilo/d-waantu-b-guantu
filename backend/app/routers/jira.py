# Path: app/routers/jira.py
# File: jira.py
# Created: 2026-05-27
# Purpose: Read-only proxy endpoints for Jira data (projects, issues, sprints)
# Caller: app/main.py
# Callees: app/services/jira.py
# Data In: HTTP requests (no body — query-string filters only)
# Data Out: JSON (normalized issue / sprint / project dicts)
# Last Modified: 2026-05-27

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services import jira as svc

router = APIRouter(prefix="/api/jira", tags=["jira"])


@router.get("/config")
def get_config() -> dict:
    """Lightweight health check — does NOT contact Jira. Returns whether the
    backend has credentials configured. The frontend uses this to decide
    whether to render the Jira UI surfaces."""
    return {
        "configured": settings.jira_configured,
        "base_url": settings.JIRA_BASE_URL if settings.jira_configured else None,
        "cache_ttl_seconds": settings.JIRA_CACHE_TTL_SECONDS,
    }


@router.get("/projects")
def list_projects() -> list[dict]:
    return svc.list_projects()


@router.get("/issues/{issue_key}")
def get_issue(issue_key: str) -> dict:
    return svc.get_issue(issue_key)


@router.get("/search")
def search_issues(
    jql: str = Query(..., description="Raw JQL query"),
    limit: int = Query(50, ge=1, le=100),
) -> list[dict]:
    return svc.search_issues(jql=jql, limit=limit)


@router.get("/projects/{project_key}/sprints")
def list_active_sprints(project_key: str) -> list[dict]:
    return svc.get_active_sprints(project_key)


@router.get("/sprints/{sprint_id}/issues")
def list_sprint_issues(sprint_id: int) -> list[dict]:
    return svc.get_sprint_issues(sprint_id)


@router.post("/cache/clear", status_code=204)
def clear_cache() -> None:
    """Admin escape hatch — drop all cached Jira responses."""
    svc.clear_cache()


@router.post("/sync")
def sync_from_jira(
    project_id: int | None = Query(None, description="Restrict to one project; omit for all"),
    db: Session = Depends(get_db),
) -> dict:
    """Mirror Jira issue status into linked DWB tickets. Jira leads.

    Returns a summary: counts of synced/changed/unmapped/errors and per-row
    details for the changed tickets.
    """
    return svc.sync_linked_tickets(db, project_id=project_id)


@router.get("/rollup")
def jira_rollup(
    project_id: int = Query(..., description="DWB project id"),
    db: Session = Depends(get_db),
) -> dict:
    """Group a project's linked tickets by their root Jira Epic and return
    per-epic completion stats. Walks one hop up for Subtask parents."""
    return svc.rollup_by_epic(db, project_id=project_id)
