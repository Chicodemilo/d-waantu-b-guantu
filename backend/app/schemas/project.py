# Path: app/schemas/project.py
# File: project.py
# Created: 2026-03-29
# Purpose: Pydantic schemas for project CRUD with gate flags
# Caller: app/routers/projects.py
# Callees: pydantic, app/config/server_repo.py
# Data In: JSON request body
# Data Out: ProjectCreate, ProjectUpdate, ProjectRead, ProjectOverheadIncrement
# Last Modified: 2026-09-16 (DWB-571: ProjectRead.runs_own_tests computed field)

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.config.server_repo import runs_own_tests as _runs_own_tests
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
    force_handoff_md: bool = True
    force_coding_standards_md: bool = False
    force_standards_audit: bool = False
    force_consolidation: bool = False


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
    force_coding_standards_md: bool | None = None
    force_standards_audit: bool | None = None
    force_consolidation: bool | None = None
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
    force_coding_standards_md: bool
    force_standards_audit: bool
    force_consolidation: bool
    capture_agent_comms: bool
    playbooks_deployed_at: datetime | None
    nodeified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def runs_own_tests(self) -> bool:
        """DWB-571: true only for the one project whose repo_path IS this
        DWB server's own repo - the sole project whose tests this server can
        honestly execute. The frontend gates the "run system tests" control
        on this field rather than recomputing the check itself; the backend
        also enforces it independently at POST /system/run-tests (a hidden
        control is not an access rule)."""
        return _runs_own_tests(self.repo_path)


class ProjectFromRepoRead(ProjectRead):
    """DWB-461: from-repo creation response. Same as ProjectRead plus a
    best-effort deploy_warning: null when the post-create .claude/ bundle
    deploy succeeded, else a short string describing why it was skipped
    (deploy failure never fails project creation)."""

    deploy_warning: str | None = None


# --- GET /{id}/ticket-token-baseline (DWB-546) -------------------------------


class TicketTokenBaselineRow(BaseModel):
    """One done ticket in the token baseline.

    tokens_used is the ATTRIBUTED value from tracking_log token_report rows
    (app/services/tracking.compute_ticket_tokens); stored_tokens_used is the
    denormalized tickets.tokens_used column, which has a manual-increment path
    that writes no tracking_log row. node_aware is a DWB-546 placeholder, False
    for every ticket until DWB-545 follow-ups can distinguish a node-aware run.
    """

    ticket_id: int
    ticket_key: str
    sprint_id: int | None
    assigned_agent_id: int | None
    assigned_agent_name: str | None
    tokens_used: int
    stored_tokens_used: int
    time_seconds: int
    completed_at: str | None
    node_aware: bool


class TicketTokenBaselineSprint(BaseModel):
    """Per-sprint aggregates.

    ticket_count counts every done ticket; the statistics cover only tickets
    with attributed tokens > 0, because a zero row is an attribution gap
    (DWB-539) rather than a free ticket. zero_token_ticket_count sizes the gap.
    """

    sprint_id: int | None
    ticket_count: int
    attributed_ticket_count: int
    zero_token_ticket_count: int
    median_tokens: float
    mean_tokens: float
    p90_tokens: float
    total_tokens: int


class TicketTokenBaselineRead(BaseModel):
    project_id: int
    ticket_count: int
    tickets: list[TicketTokenBaselineRow]
    sprints: list[TicketTokenBaselineSprint]
