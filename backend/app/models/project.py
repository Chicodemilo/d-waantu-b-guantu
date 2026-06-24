# Path: app/models/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Project ORM model with status enum, sprint gate flags, Jira fields, and Jira sync state (DWB-342)
# Caller: app/services/project.py, sprint.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Project, ProjectStatus
# Last Modified: 2026-06-10

import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, String, Text, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class JiraSyncStatus(str, enum.Enum):
    """DWB-342: project-level Jira sync state.

    - idle:    no sync in flight, no record of a previous run on this project
    - running: a sync is in progress (POST /api/projects/{id}/jira-sync
               sets this; subsequent POSTs return 409 until done/error)
    - done:    most recent sync finished cleanly
    - error:   most recent sync raised; counts may be partial. The
               concurrency lock is released on error so the operator can
               retry without manual intervention.
    """

    idle = "idle"
    running = "running"
    done = "done"
    error = "error"


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
    force_handoff_md: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    force_consolidation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # DWB-446: gates SendMessage agent-comms capture per project. Default TRUE;
    # when false POST /api/hooks/agent-message returns 200 and inserts nothing.
    capture_agent_comms: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    playbooks_deployed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # DWB-342: project-level Jira sync state. Used by the manual sync
    # endpoint to enforce single-sync concurrency, render the
    # last-synced-at header, and show the last run's per-bucket counts.
    last_jira_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_jira_sync_status: Mapped[JiraSyncStatus] = mapped_column(
        Enum(JiraSyncStatus), nullable=False, default=JiraSyncStatus.idle
    )
    last_jira_sync_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
