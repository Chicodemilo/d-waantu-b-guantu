# Path: app/schemas/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for project CRUD with gate flags
# Caller: app/routers/projects.py
# Callees: pydantic
# Data In: JSON request body
# Data Out: ProjectCreate, ProjectUpdate, ProjectRead, ProjectOverheadIncrement
# Last Modified: 2026-06-25 (DWBG-021 repo_url computed field)

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.project import ProjectStatus
from app.services.repo_url import derive_repo_web_url


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
    force_handoff_md: bool = True
    force_consolidation: bool = False
    # DWBG-014: LLM session-writeup generation gate, default ON.
    force_session_writeup: bool = True


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
    force_handoff_md: bool | None = None
    force_consolidation: bool | None = None
    # DWBG-014: LLM session-writeup generation gate (PATCH off to disable).
    force_session_writeup: bool | None = None
    # DWB-446: per-project SendMessage agent-comms capture gate.
    capture_agent_comms: bool | None = None


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
    force_handoff_md: bool
    force_consolidation: bool
    force_session_writeup: bool
    capture_agent_comms: bool
    playbooks_deployed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def repo_url(self) -> str | None:
        """DWBG-021: GitHub web base derived on read from the project's git
        remote (e.g. https://github.com/owner/repo). null when there is no git
        remote, the path is not a repo, or the remote is not a recognizable
        GitHub remote. Computed (not persisted) so it is always fresh and needs
        no migration; the derive helper is best-effort and never raises."""
        return derive_repo_web_url(self.repo_path)


class ProjectFromRepoRead(ProjectRead):
    """DWB-461: from-repo creation response. Same as ProjectRead plus a
    best-effort deploy_warning: null when the post-create .claude/ bundle
    deploy succeeded, else a short string describing why it was skipped
    (deploy failure never fails project creation)."""

    deploy_warning: str | None = None
