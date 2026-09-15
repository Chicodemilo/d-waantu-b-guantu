# Path: app/routers/node_exclusions.py
# File: node_exclusions.py
# Created: 2026-09-15
# Purpose: CRUD API for per-project node-scan exclusions (DWB-549): list (seeding the shipped defaults on first use), add one, delete one. Backs the exclusions manager UI (DWB-552).
# Caller: app/main.py
# Callees: app/services/node_exclusion.py
# Data In: HTTP GET/POST/DELETE under /api/projects/{project_id}/node-exclusions
# Data Out: NodeExclusionRead / NodeExclusionRead[] / 204
# Last Modified: 2026-09-15

"""Exclusion rows are per project and user-editable.

Deleting a seeded default is permanent (the project's seeded flag is already
set), which is the whole reason this is DB state rather than config.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.node_exclusion import NodeExclusionCreate, NodeExclusionRead
from app.services import node_exclusion as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["node-exclusions"])

_STATUS_BY_CODE = {
    "project_not_found": 404,
    "not_found": 404,
    "invalid_pattern": 400,
    "duplicate": 409,
}


def _http(e: svc.NodeExclusionError) -> HTTPException:
    return HTTPException(_STATUS_BY_CODE.get(e.code, 400), e.detail)


@router.get(
    "/{project_id}/node-exclusions", response_model=list[NodeExclusionRead]
)
def list_node_exclusions(project_id: int, db: Session = Depends(get_db)):
    """This project's exclusion rows, oldest first.

    First call seeds the shipped defaults as ordinary rows; later calls never
    re-seed, so a deleted default stays deleted."""
    try:
        rows = svc.list_exclusions(db, project_id)
    except svc.NodeExclusionError as e:
        raise _http(e)
    db.commit()
    return rows


@router.post(
    "/{project_id}/node-exclusions",
    response_model=NodeExclusionRead,
    status_code=201,
)
def add_node_exclusion(
    project_id: int, data: NodeExclusionCreate, db: Session = Depends(get_db)
):
    """Add one repo-relative path or glob. 400 names why a pattern was refused
    (absolute, escaping the repo root, empty, too long); 409 on a duplicate."""
    try:
        row = svc.add_exclusion(db, project_id, data.pattern)
    except svc.NodeExclusionError as e:
        raise _http(e)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{project_id}/node-exclusions/{exclusion_id}", status_code=204)
def delete_node_exclusion(
    project_id: int, exclusion_id: int, db: Session = Depends(get_db)
):
    """Remove one exclusion. Permanent, including for a seeded default."""
    try:
        svc.delete_exclusion(db, project_id, exclusion_id)
    except svc.NodeExclusionError as e:
        raise _http(e)
    db.commit()
