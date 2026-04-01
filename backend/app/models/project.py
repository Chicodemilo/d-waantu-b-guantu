# Path: app/models/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Project ORM model with status enum and sprint gate flags
# Caller: app/services/project.py, sprint.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Project, ProjectStatus
# Last Modified: 2026-03-29

import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    prefix: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), nullable=False, default=ProjectStatus.active
    )
    tl_overhead_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pm_overhead_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tl_overhead_time_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pm_overhead_time_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    repo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jira_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jira_project_key: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    force_headers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    force_test_coverage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    force_test_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    force_initial_md: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    force_architecture_md: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    sprints: Mapped[list["Sprint"]] = relationship(back_populates="project")  # noqa: F821
    epics: Mapped[list["Epic"]] = relationship(back_populates="project")  # noqa: F821
    project_agents: Mapped[list["ProjectAgent"]] = relationship(back_populates="project")  # noqa: F821
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="project")  # noqa: F821
    alerts: Mapped[list["Alert"]] = relationship(back_populates="project")  # noqa: F821
    instructions: Mapped[list["Instruction"]] = relationship(back_populates="project")  # noqa: F821
    activity_logs: Mapped[list["ActivityLog"]] = relationship(back_populates="project")  # noqa: F821
    test_results: Mapped[list["TestResult"]] = relationship(back_populates="project")  # noqa: F821
