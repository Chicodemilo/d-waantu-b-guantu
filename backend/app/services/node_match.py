# Path: app/services/node_match.py
# File: node_match.py
# Created: 2026-09-14 (DWB-523)
# Purpose: Read surface over the node graph - list nodes (weight-ordered,
#          optionally filtered by pointer kind) and match query text to nodes,
#          returning each match with its pointers + derived neighbors. Neighbors
#          are NOT stored (DWB-522): two nodes are connected iff they have
#          pointers sharing a ref, computed here at query time. This is the shape
#          retrieval (DWB-524) and the graph view consume, so it is frozen early.
# Caller: app/routers/nodes.py
# Callees: app/services/node_registry (node_tokens), app/models/node
# Data In: db: Session, project_id: int, optional kind filter / query text
# Data Out: Node lists; (query_tags, [(node, neighbors)]) for match
# Last Modified: 2026-09-14 (DWB-523)

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.node import Node, NodePointer, NodePointerKind
from app.services.node_registry import VALID_KINDS, node_tokens


@dataclass
class Neighbor:
    """A neighbor node + the refs it shares with the matched node."""

    node: Node
    shared_refs: list[str]


def list_nodes(
    db: Session, project_id: int, *, kind: str | None = None
) -> list[Node]:
    """List a project's nodes, weight desc then tag asc (deterministic).

    When ``kind`` is given, only nodes that have at least one pointer of that
    domain are returned (the graph view's kind filter). Pointers are eager-loaded
    so the caller renders the full node without an N+1.
    """
    q = (
        select(Node)
        .where(Node.project_id == project_id)
        .options(selectinload(Node.pointers))
        .order_by(Node.weight.desc(), Node.tag.asc())
    )
    if kind is not None:
        if kind not in VALID_KINDS:
            raise ValueError(
                f"kind '{kind}' is not one of {sorted(VALID_KINDS)}"
            )
        q = q.where(
            Node.id.in_(
                select(NodePointer.node_id).where(
                    NodePointer.project_id == project_id,
                    NodePointer.kind == NodePointerKind(kind),
                )
            )
        )
    return list(db.execute(q).scalars().all())


def match_nodes(
    db: Session, project_id: int, text: str
) -> tuple[list[str], list[tuple[Node, list[Neighbor]]]]:
    """Match query text to nodes and derive each match's neighbors.

    Returns ``(query_tags, matches)`` where ``query_tags`` is the normalized +
    stemmed tokenization of ``text`` (same pipeline as registration, so the query
    tokens line up with stored tags) and ``matches`` is a weight-ordered list of
    (node, neighbors). A neighbor is any OTHER node in the project that shares a
    pointer ref with the matched node; ``shared_refs`` is the evidence.
    """
    query_tags = sorted(node_tokens(text))
    if not query_tags:
        return [], []

    matched = list(
        db.execute(
            select(Node)
            .where(Node.project_id == project_id, Node.tag.in_(query_tags))
            .options(selectinload(Node.pointers))
            .order_by(Node.weight.desc(), Node.tag.asc())
        )
        .scalars()
        .all()
    )
    if not matched:
        return query_tags, []

    matches: list[tuple[Node, list[Neighbor]]] = []
    for node in matched:
        matches.append((node, _neighbors_of(db, project_id, node)))
    return query_tags, matches


def _neighbors_of(db: Session, project_id: int, node: Node) -> list[Neighbor]:
    """Derive neighbors of ``node`` from shared pointer refs (DWB-522).

    The matched node's refs are joined against every OTHER node's pointers; a
    node sharing >=1 ref is a neighbor. Ordered by shared-ref count desc, then
    weight desc, then tag asc for a stable, meaningful order.
    """
    refs = {p.ref for p in node.pointers}
    if not refs:
        return []

    rows = db.execute(
        select(
            NodePointer.node_id,
            NodePointer.ref,
            Node.tag,
            Node.weight,
        )
        .join(Node, Node.id == NodePointer.node_id)
        .where(
            NodePointer.project_id == project_id,
            NodePointer.ref.in_(refs),
            NodePointer.node_id != node.id,
        )
    ).all()

    by_node: dict[int, dict] = {}
    for node_id, ref, tag, weight in rows:
        entry = by_node.setdefault(
            node_id, {"tag": tag, "weight": weight, "refs": set()}
        )
        entry["refs"].add(ref)

    neighbors = [
        Neighbor(
            node=_NeighborStub(
                id=nid, tag=e["tag"], weight=e["weight"]
            ),
            shared_refs=sorted(e["refs"]),
        )
        for nid, e in by_node.items()
    ]
    neighbors.sort(
        key=lambda n: (-len(n.shared_refs), -n.node.weight, n.node.tag)
    )
    return neighbors


@dataclass
class _NeighborStub:
    """Lightweight neighbor identity (id/tag/weight) - avoids loading the full
    ORM node + its pointers just to render a neighbor summary."""

    id: int
    tag: str
    weight: int
