# Path: app/models/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Project ORM model with status enum, sprint gate flags, Jira fields, and Jira sync state (DWB-342)
# Caller: app/services/project.py, sprint.py
# Callees: app/database.Base
# Data In: DB rows
# Data Out: Project, ProjectStatus, MemoryMode
# Last Modified: 2026-09-30 (DWB-593: memory_mode gains adopting + reverting)

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class MemoryMode(str, enum.Enum):
    """DWB-584: which memory system this project's agents run on.

    - stock:        one markdown file per agent with a token ceiling, injected
                    whole at spawn. The system as it has always worked.
    - human_memory: memories become rows across four holders with a derived
                    score and a journal. Spec: docs/human_memory_spec.md.

    - adopting:     mid-transition INTO human_memory (DWB-593).
    - reverting:    mid-transition back OUT to stock (DWB-593).

    Per spec section 7 hard rule 1, when human_memory is on it is the ONLY
    memory: stock memory is not written, not read, not consulted. The two are a
    choice, never a fallback pair, because two memories that both look
    authoritative and disagree is the failure this whole design exists to
    avoid.

    THE TWO TRANSITION STATES ARE NOT SEALED, AND THAT IS THE WHOLE POINT OF
    DWB-593. Stock stays authoritative for reads AND writes throughout a
    transition, so an agent spawning mid-flight reads its memory exactly as it
    does today and notices nothing. The seal and the flip happen together at
    cutover, as one act.

    That property costs nothing to maintain because the single `memory_mode`
    predicate in the backend (app/services/memory_mode.py) asks
    `== human_memory` rather than `!= stock`. IF YOU ARE TIDYING THAT LINE, DO
    NOT: rewriting it as `!= stock` seals a project the moment it starts
    adopting, against a store that is still empty, which is precisely the
    amnesia bug DWB-593 exists to make unreachable. A test asserts it.

    ORDER IS SIGNIFICANT. MySQL stores an ENUM as the ordinal of its value, so
    the two new members are APPENDED. Inserting either in the middle renumbers
    `human_memory` on every existing row.
    """

    stock = "stock"
    human_memory = "human_memory"
    adopting = "adopting"
    reverting = "reverting"


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
    force_coding_standards_md: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # DWB-017: sprint gate requiring a PASSING standards audit for the sprint
    # before close. COMPLEMENTS force_coding_standards_md (which only asserts the
    # standards DOC exists) - this asserts the code actually conforms. Keep both.
    # Default OFF (opt-in).
    force_standards_audit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
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
    # DWB-527: last time the operator-invoked nodeify full pass ran for this
    # project (rebuilt nodes from memory + docs + git). Null = never nodeified.
    nodeified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # DWB-549: whether the shipped node-scan exclusion defaults have been seeded
    # as rows for this project. A flag, not "is the row set empty", so that
    # deleting a seeded default is PERMANENT rather than being re-added by the
    # next read.
    node_exclusions_seeded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # DWB-584: human_memory mode. Per-project toggle, defaults to stock, and
    # per the spec the mode never leaves beta, which is why it is versioned.
    # memory_schema_version is stamped so v1 content stays readable by v2
    # tooling. Switching modes rewrites every memory the project has, so the
    # UI that sets this must warn first (spec section 6).
    memory_mode: Mapped[MemoryMode] = mapped_column(
        Enum(MemoryMode),
        nullable=False,
        default=MemoryMode.stock,
        server_default=MemoryMode.stock.value,
    )
    memory_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # DWB-584 / DWB-590: TOP-OFF. THESE TWO COLUMNS ARE DELIBERATELY UNRELATED
    # TO THE MEMORY COLUMNS ABOVE THEM. Miles ruled top-off INDEPENDENT of
    # memory mode, and the spec reached the same conclusion in section 8: it is
    # orthogonal, about repetition and drift, not memory structure. They sit
    # here because DWB-584 held the sprint's only migration slot, which is a
    # delivery fact and nothing else. Top-off must work on a project in stock
    # mode, and DWB-590's logic must not read memory_mode. Schema colocation is
    # not feature coupling.
    topoff_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    topoff_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
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
