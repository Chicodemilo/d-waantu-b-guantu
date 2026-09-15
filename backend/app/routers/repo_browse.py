# Path: app/routers/repo_browse.py
# File: repo_browse.py
# Created: 2026-09-15
# Purpose: Read-only directory listing under a project's repo_path (DWB-553), backing the exclusions browser in the DWB-552 manager. One level per call; every path is proven to stay inside the repo root.
# Caller: app/main.py
# Callees: app/services/repo_browse.py, app/services/project.py
# Data In: GET /api/projects/{project_id}/repo-directories?parent=<repo-relative>
# Data Out: RepoDirectoryListing
# Last Modified: 2026-09-15

"""Browse the repo tree. Read-only: this router writes nothing, anywhere."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.schemas.repo_browse import RepoDirectoryListing
from app.services import repo_browse as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["repo-browse"])

_STATUS_BY_CODE = {
    "no_repo_path": 400,
    "invalid_path": 400,
    "not_found": 404,
}


@router.get(
    "/{project_id}/repo-directories", response_model=RepoDirectoryListing
)
def list_repo_directories(
    project_id: int,
    parent: str = Query(
        "",
        description="Repo-relative directory to list; empty (the default) is the repo root",
    ),
    db: Session = Depends(get_db),
):
    """Child directories one level under ``parent``, repo-relative.

    400 names the reason for an absolute path, a traversal attempt, a path that
    escapes the root once resolved, or a project with no repo_path. 404 for a
    directory that does not exist. Dot directories and node_modules are never
    listed.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, f"Project {project_id} not found")
    try:
        return svc.list_directories(project.repo_path, parent)
    except svc.RepoBrowseError as e:
        raise HTTPException(_STATUS_BY_CODE.get(e.code, 400), e.detail)
