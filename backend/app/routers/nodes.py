# Path: app/routers/nodes.py
# File: nodes.py
# Created: 2026-09-14 (DWB-523)
# Purpose: Node read API + the nodeify write route. GET /nodes lists a project's
#          nodes (weight-ordered, optional kind filter); GET /nodes/match?text=...
#          normalizes the query and returns matching nodes with pointers + derived
#          neighbors (the FROZEN surface retrieval DWB-524 + the graph view read).
#          POST /nodeify (DWB-527) is the operator-invoked idempotent full rebuild,
#          same lane as deploy-playbooks.
# Caller: app/main.py
# Callees: app/services/node_match, app/services/node_touch, app/services/project
# Data In: HTTP GET requests; POST /nodeify
# Data Out: list[NodeRead]; NodeMatchResponse; NodeifyResponse
# Last Modified: 2026-09-14 (DWB-527: nodeify endpoint)

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.node import (
    NodeifyResponse,
    NodeMatchNode,
    NodeMatchResponse,
    NodeNeighborRead,
    NodePointerRead,
    NodeRead,
)
from app.services import node_match as match_svc
from app.services import node_touch as touch_svc
from app.services import project as project_svc

router = APIRouter(prefix="/api", tags=["nodes"])


def _require_project(db: Session, project_id: int):
    project = project_svc.get_project(db, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _pointer_reads(node) -> list[NodePointerRead]:
    return [NodePointerRead.model_validate(p) for p in node.pointers]


@router.get("/projects/{project_id}/nodes", response_model=list[NodeRead])
def list_project_nodes(
    project_id: int,
    kind: str | None = Query(
        None,
        description="Optional pointer-domain filter: code|memory|doc|ticket|session",
    ),
    db: Session = Depends(get_db),
):
    """List a project's nodes, weight-ordered (desc), each with its pointers.
    ``kind`` restricts to nodes grounded in that domain."""
    _require_project(db, project_id)
    try:
        nodes = match_svc.list_nodes(db, project_id, kind=kind)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return [
        NodeRead(
            id=n.id,
            project_id=n.project_id,
            tag=n.tag,
            weight=n.weight,
            pointers=_pointer_reads(n),
        )
        for n in nodes
    ]


@router.get(
    "/projects/{project_id}/nodes/match", response_model=NodeMatchResponse
)
def match_project_nodes(
    project_id: int,
    text: str = Query(..., description="Free text to match against node tags"),
    db: Session = Depends(get_db),
):
    """Normalize ``text`` to tags and return matching nodes, each with its full
    pointer list and derived neighbors (nodes sharing a pointer ref)."""
    _require_project(db, project_id)
    query_tags, matches = match_svc.match_nodes(db, project_id, text)
    nodes = [
        NodeMatchNode(
            id=node.id,
            project_id=node.project_id,
            tag=node.tag,
            weight=node.weight,
            pointers=_pointer_reads(node),
            neighbors=[
                NodeNeighborRead(
                    id=nb.node.id,
                    tag=nb.node.tag,
                    weight=nb.node.weight,
                    shared_refs=nb.shared_refs,
                )
                for nb in neighbors
            ],
        )
        for node, neighbors in matches
    ]
    return NodeMatchResponse(query=text, query_tags=query_tags, nodes=nodes)


@router.post("/projects/{project_id}/nodeify", response_model=NodeifyResponse)
def nodeify_project(project_id: int, db: Session = Depends(get_db)):
    """Operator-invoked idempotent full pass (nodeify / renodify, DWB-527).

    Rebuilds the project's nodes from the memory corpus + docs + git history:
    refreshes rotted line/sha refs, prunes pointers whose source vanished, and
    stamps project.nodeified_at. Re-running is a no-op. Same lane as
    deploy-playbooks (no request body)."""
    _require_project(db, project_id)
    try:
        result = touch_svc.nodeify_project(db, project_id)
    except touch_svc.NodeTouchError as e:
        status = 404 if e.code == "project_not_found" else 400
        raise HTTPException(status, e.detail)
    return NodeifyResponse(
        project_id=result.project_id,
        nodeified_at=result.nodeified_at,
        source_counts=result.source_counts,
        grounded=result.grounded,
        pruned=result.pruned,
        suppressed=result.suppressed,
        pointers_written=result.pointers_written,
    )
