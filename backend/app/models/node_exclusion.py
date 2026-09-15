# Path: app/models/node_exclusion.py
# File: node_exclusion.py
# Created: 2026-09-15
# Purpose: Per-project node-scan exclusion rows (DWB-549). One row = one repo-relative path or glob the grounding lanes must skip. User-editable from the nodes page, so this is DB state rather than config; the shipped defaults are seeded as ordinary deletable rows.
# Caller: app/services/node_exclusion.py, app/routers/node_exclusions.py
# Callees: app/database.Base
# Data In: project_id + pattern
# Data Out: NodeExclusion ORM rows
# Last Modified: 2026-09-15

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NodeExclusion(Base):
    """A path or glob the node-grounding lanes skip for ONE project.

    Patterns are repo-relative because that is exactly the shape of a pointer
    ref, so what a user types in the manager matches what the matcher compares
    (see app/config/node_scan.py for the grammar). Nothing here is special-cased:
    a seeded default is an ordinary row and deleting it is permanent, which is
    why the "have we seeded yet" flag lives on the project rather than being
    inferred from the row set being empty.
    """

    __tablename__ = "node_exclusions"
    __table_args__ = (
        UniqueConstraint("project_id", "pattern", name="uq_node_exclusions_project_pattern"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
