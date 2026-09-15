# Path: app/schemas/node.py
# File: node.py
# Created: 2026-09-14 (DWB-523)
# Purpose: Pydantic read schemas for the node match/list API - the FROZEN read
#          surface consumed by retrieval (DWB-524) and the future graph view.
#          A node carries its weight + full pointer list; the match endpoint adds
#          derived neighbors (nodes sharing a pointer ref). No write schemas -
#          nodes are produced by the registration service (DWB-522) and the
#          nodeify pass (DWB-527), never by a client POST body.
# Caller: app/routers/nodes.py
# Callees: pydantic
# Data In: ORM Node / NodePointer rows (via service)
# Data Out: NodePointerRead, NodeRead, NodeNeighborRead, NodeMatchNode,
#           NodeMatchResponse
# Last Modified: 2026-09-14 (DWB-523)

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NodePointerRead(BaseModel):
    """One grounding of a node: WHERE it lives, never WHAT."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    ref: str
    sha: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class NodeRead(BaseModel):
    """A LIGHT node with its full pointer list. Used by the list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    tag: str
    weight: int
    pointers: list[NodePointerRead] = []


class NodeNeighborRead(BaseModel):
    """A node connected to the matched node via one or more shared pointer refs.

    Edges are NOT stored (DWB-522): this connection is derived at query time from
    pointers that share a ref. ``shared_refs`` lists the refs the two nodes have
    in common (the evidence for the edge).
    """

    id: int
    tag: str
    weight: int
    shared_refs: list[str]


class NodeMatchNode(NodeRead):
    """A matched node plus its derived neighbors (the match-endpoint shape)."""

    neighbors: list[NodeNeighborRead] = []


class NodeMatchResponse(BaseModel):
    """Response for GET /nodes/match. ``query_tags`` is the normalized+stemmed
    tokenization of the query text, so a caller can see exactly what matched."""

    query: str
    query_tags: list[str]
    nodes: list[NodeMatchNode]


class NodeifyResponse(BaseModel):
    """Response for POST /nodeify (DWB-527): the full-pass report."""

    project_id: int
    nodeified_at: str
    source_counts: dict[str, int]
    grounded: int
    pruned: int
    suppressed: int
    pointers_written: int
