# Path: app/models/node.py
# File: node.py
# Created: 2026-09-14
# Purpose: Node + NodePointer ORM models (DWB-522). A node is LIGHT (Miles
#          ruling): one row per normalized tag that knows WHERE it is grounded,
#          never WHAT the content is. NodePointer rows carry the WHERE (kind +
#          ref + optional sha + optional line range). Node-to-node edges are NOT
#          stored - a connection between two nodes is derived at query time from
#          pointers that share the same ref (DWB-523).
# Caller: app/services/node_registry.py, app/services/node_match.py, alembic
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Node, NodePointer, NodePointerKind
# Last Modified: 2026-09-14

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NodePointerKind(str, enum.Enum):
    """The pointer DOMAIN. Grounding (DWB-522) keys off distinct domains: a tag
    only becomes a node once its pointers span 2 or more of these."""

    code = "code"
    memory = "memory"
    doc = "doc"
    ticket = "ticket"
    session = "session"


class Node(Base):
    """A LIGHT node: one normalized tag, grounded in 2+ pointer domains.

    A node stores no content - only its tag, a ranking weight (the count of
    pointers grounding it), and timestamps. The WHERE lives entirely in the
    NodePointer children. Uniqueness is per (project_id, tag): a normalized tag
    collision merges onto one node rather than creating a duplicate (the
    registration service normalizes before lookup, so 'Nodes' and 'node' land on
    the same row).

    Edges are NOT a table. Two nodes are connected iff they have pointers that
    share a ref; that neighbor set is derived at query time (DWB-523).
    """

    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("project_id", "tag", name="uq_nodes_project_tag"),
        Index("ix_nodes_project_id", "project_id"),
        Index("ix_nodes_project_weight", "project_id", "weight"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(255), nullable=False)
    # Ranking weight (>=1): the number of DISTINCT (kind, ref) groundings for this
    # node - i.e. how many distinct places ground the tag, not the raw pointer
    # count. Per-line pointer lanes (DWB-525/526) can emit many pointers for one
    # (kind, ref); weight counts that source once so ranking reflects grounding
    # breadth. Recomputed on every registration pass; consumers sort by it desc.
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    pointers: Mapped[list["NodePointer"]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class NodePointer(Base):
    """One grounding of a node: WHERE the tag was seen, never WHAT.

    A pointer belongs to a grounded node (node_id is set), so pointers only ever
    exist for tags that already cleared the 2-domain grounding rule (DWB-522).
    `tag` is denormalized onto the pointer so the registration service can count
    a tag's domains across refs with a single indexed scan and so pointers that
    share a ref can be joined for neighbor derivation (DWB-523).

    - kind: the domain (code|memory|doc|ticket|session).
    - ref:  the WHERE within that domain - a file path, git sha, ticket key,
            memory entry heading, or session id. (project_id, kind, ref) is the
            refresh scope: a re-registration of a ref replaces its pointers.
    - sha / line_start / line_end: optional provenance for code/doc pointers so a
            rotted line ref can be refreshed to the current sha (DWB-527).
    """

    __tablename__ = "node_pointers"
    __table_args__ = (
        Index("ix_node_pointers_project_tag", "project_id", "tag"),
        Index("ix_node_pointers_project_kind_ref", "project_id", "kind", "ref"),
        Index("ix_node_pointers_project_ref", "project_id", "ref"),
        Index("ix_node_pointers_node_id", "node_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False
    )
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[NodePointerKind] = mapped_column(
        Enum(NodePointerKind), nullable=False
    )
    ref: Mapped[str] = mapped_column(String(500), nullable=False)
    sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    node: Mapped["Node"] = relationship(back_populates="pointers")
