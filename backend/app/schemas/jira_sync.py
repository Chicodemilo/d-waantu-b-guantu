# Path: app/schemas/jira_sync.py
# File: jira_sync.py
# Created: 2026-06-10
# Purpose: Pydantic schemas for the DWB-342 unified Jira table endpoints (list + sync trigger + sync status)
# Caller: app/routers/projects.py (jira-tickets, jira-sync, jira-sync/status)
# Callees: pydantic
# Data In: HTTP request/response bodies
# Data Out: JiraTicketRow, JiraTicketsListResponse, JiraSyncStartResponse, JiraSyncStatusResponse
# Last Modified: 2026-06-10

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JiraTicketRow(BaseModel):
    """One row in the unified Jira table - the 10 columns DWB-342 surfaces.

    Combines DWB-side fields (ticket_id, dwb_key, dwb_sprint, dwb_status)
    with the cached Jira snapshot. last_synced_at is the per-row cache
    freshness stamp. Sortable on every column; fuzzy search hits all
    string fields server-side.
    """

    model_config = ConfigDict(from_attributes=True)

    # DWB side
    ticket_id: int
    dwb_key: str
    dwb_sprint: str | None
    dwb_status: str
    title: str
    created_at: datetime
    updated_at: datetime

    # Jira side (cached)
    jira_key: str
    jira_sprint: str | None
    jira_status: str | None
    jira_assignee: str | None
    jira_reporter: str | None
    jira_title: str | None
    jira_created_at: datetime | None
    jira_updated_at: datetime | None
    last_synced_at: datetime | None
    # DWB-362: 11th column on the unified Jira table.
    jira_issue_type: str | None = None
    # DWB-363: 12th column - epic key + resolved name. The frontend
    # renders the key prominently and shows the name in a tooltip.
    jira_epic_key: str | None = None
    jira_epic_name: str | None = None
    # DWB-364: 13th column - parent Jira key, subtasks only. Frontend
    # renders the key directly under the Parent column header; None
    # rows show the '-' placeholder.
    jira_parent_key: str | None = None


class JiraTicketsListResponse(BaseModel):
    """GET /api/projects/{id}/jira-tickets response."""

    project_id: int
    project_prefix: str
    total: int
    limit: int
    offset: int
    rows: list[JiraTicketRow]


class JiraSyncStartResponse(BaseModel):
    """POST /api/projects/{id}/jira-sync - 202 Accepted response."""

    project_id: int
    status: str
    started_at: datetime


class JiraSyncStatusResponse(BaseModel):
    """GET /api/projects/{id}/jira-sync/status response.

    Polled by the UI to detect sync completion. ``status`` mirrors the
    Project.last_jira_sync_status enum. ``counts`` is None until at
    least one sync has finished (or errored).
    """

    project_id: int
    status: str
    last_synced_at: datetime | None
    counts: dict | None
