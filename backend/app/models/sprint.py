# Path: app/models/sprint.py
# File: sprint.py
# Created: 2026-03-29
# Purpose: Sprint ORM model with status enum + single-active-per-project invariant
# Caller: app/services/sprint.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Sprint, SprintStatus
# Last Modified: 2026-06-09

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SprintStatus(str, enum.Enum):
    planned = "planned"
    active = "active"
    completed = "completed"


class Sprint(Base):
    """A sprint groups tickets within an epic. Single active invariant
    (DWB-331): at most one row per project_id with status=active.

    Enforced by a STORED generated column (`is_active` = 1 when status =
    active else NULL) plus a UNIQUE(project_id, is_active) index. Same
    pattern as Epic.is_in_progress and DwbSession.is_open (DWB-335).
    """

    __tablename__ = "sprints"
    __table_args__ = (
        Index(
            "uq_sprints_one_active_per_project",
            "project_id",
            "is_active",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id"), nullable=False, index=True
    )
    epic_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("epics.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    sprint_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SprintStatus] = mapped_column(
        Enum(SprintStatus), nullable=False, default=SprintStatus.planned
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Single-active marker — 1 when status is active, NULL else. The
    # (project_id, is_active) UNIQUE index uses this to enforce
    # one-active-sprint-per-project.
    is_active: Mapped[int | None] = mapped_column(
        SmallInteger,
        Computed(
            "(CASE WHEN status = 'active' THEN 1 ELSE NULL END)",
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
    project: Mapped["Project"] = relationship(back_populates="sprints")  # noqa: F821
    epic: Mapped["Epic"] = relationship()  # noqa: F821
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="sprint")  # noqa: F821
