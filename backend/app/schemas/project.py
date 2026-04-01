# Path: app/schemas/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for project CRUD with gate flags
# Caller: app/routers/projects.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: ProjectCreate, ProjectUpdate, ProjectRead, ProjectOverheadIncrement
# Last Modified: 2026-03-29

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.project import ProjectStatus


class ProjectCreate(BaseModel):
    prefix: str
    name: str
    description: str | None = None
    status: ProjectStatus = ProjectStatus.active
    repo_path: str | None = None
    jira_base_url: str | None = None
    jira_project_key: str | None = None
    force_headers: bool = False
    force_test_coverage: bool = False
    force_test_run: bool = False
    force_initial_md: bool = False
    force_architecture_md: bool = False


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None
    tl_overhead_tokens: int | None = None
    pm_overhead_tokens: int | None = None
    tl_overhead_time_seconds: int | None = None
    pm_overhead_time_seconds: int | None = None
    repo_path: str | None = None
    jira_base_url: str | None = None
    jira_project_key: str | None = None
    force_headers: bool | None = None
    force_test_coverage: bool | None = None
    force_test_run: bool | None = None
    force_initial_md: bool | None = None
    force_architecture_md: bool | None = None


class ProjectOverheadIncrement(BaseModel):
    role: str  # "team_lead" or "pm"
    tokens_used: int = 0
    time_spent_seconds: int = 0


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prefix: str
    name: str
    description: str | None
    status: ProjectStatus
    repo_path: str | None
    jira_base_url: str | None
    jira_project_key: str | None
    tl_overhead_tokens: int
    pm_overhead_tokens: int
    tl_overhead_time_seconds: int
    pm_overhead_time_seconds: int
    force_headers: bool
    force_test_coverage: bool
    force_test_run: bool
    force_initial_md: bool
    force_architecture_md: bool
    created_at: datetime
    updated_at: datetime
