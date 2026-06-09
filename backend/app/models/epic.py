# Path: app/models/epic.py
# File: epic.py
# Created: 2026-03-29
# Purpose: Epic ORM model with status enum + single-in_progress-per-project invariant
# Caller: app/services/epic.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Epic, EpicStatus
# Last Modified: 2026-06-09

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EpicStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    completed = "completed"


class Epic(Base):
    """An epic groups sprints within a project. Single in_progress invariant
    (DWB-331): at most one row per project_id with status=in_progress.

    Enforced by a STORED generated column (`is_in_progress` = 1 when status
    = in_progress else NULL) plus a UNIQUE(project_id, is_in_progress)
    index. MySQL treats NULL as distinct in UNIQUE, so only the
    in_progress slot is constrained; open + completed rows can have any
    cardinality. Same pattern as DwbSession (DWB-335).
    """

    __tablename__ = "epics"
    __table_args__ = (
        Index(
            "uq_epics_one_in_progress_per_project",
            "project_id",
            "is_in_progress",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EpicStatus] = mapped_column(
        Enum(EpicStatus), nullable=False, default=EpicStatus.open
    )

    # Single-in_progress marker — 1 when status is in_progress, NULL else.
    # The (project_id, is_in_progress) UNIQUE index uses this to enforce
    # one-in_progress-epic-per-project.
    is_in_progress: Mapped[int | None] = mapped_column(
        SmallInteger,
        Computed(
            "(CASE WHEN status = 'in_progress' THEN 1 ELSE NULL END)",
            persisted=True,
        ),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="epics")  # noqa: F821
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="epic")  # noqa: F821
