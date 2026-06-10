# Path: app/models/jira_ticket_snapshot.py
# File: jira_ticket_snapshot.py
# Created: 2026-06-10
# Purpose: Cached snapshot of Jira-side fields for a DWB ticket - read-only mirror, refreshed by manual sync (DWB-342)
# Caller: app/services/jira_sync.py, app/routers/jira_sync.py
# Callees: app/database.Base
# Data In: Jira REST responses (via jira_sync), DWB ticket ids
# Data Out: JiraTicketSnapshot rows
# Last Modified: 2026-06-10

"""One-to-one cache of Jira-side fields per linked DWB ticket (DWB-342).

Sibling table (NOT extra columns on tickets) because:
  - DWB itself is non-Jira and carries 250+ tickets; widening the canonical
    table with always-null columns for non-Jira projects is wasteful.
  - The cache is wholly derived from Jira and can be wiped + rebuilt
    without risk to DWB-owned data; isolation is cleanest in a separate
    table.
  - DWB-342 explicitly forbids writes back to Jira; keeping the cache
    apart makes it obvious which columns the sync job owns.

ON DELETE CASCADE on ticket_id so deleting a DWB ticket also drops its
cached snapshot. The reverse is not modeled - dropping the snapshot
table or row leaves the canonical ticket untouched (that's the point of
the separation).

last_synced_at is the per-row stamp (last time THIS ticket's snapshot
was refreshed). The project-level last sync time + counts live on the
Project row (last_jira_sync_at etc); the project row is the
list-page-header source of truth, the per-row stamp here is the
table-cell source of truth.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JiraTicketSnapshot(Base):
    __tablename__ = "jira_ticket_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # One-to-one: at most one snapshot per ticket. UNIQUE enforces it.
    ticket_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # The Jira key is duplicated here (also on tickets.jira_issue_key) so the
    # list endpoint can serve the cache row without joining tickets. Kept in
    # sync by the sync job; tickets.jira_issue_key remains the canonical link.
    jira_issue_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Snapshot fields (all nullable; Jira may omit any of these on a given issue).
    jira_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    jira_sprint_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jira_assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jira_reporter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jira_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jira_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    jira_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    jira_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # DWB-362: 11th column on the unified Jira table - Jira's issue type
    # (Task / Story / Bug / Sub-task / Epic / etc.). Sourced from
    # issue.fields.issuetype.name via app.services.jira._normalize_issue.
    # NULL on snapshots created before the DWB-362 sync ran; the list
    # endpoint serves NULL through to the UI for the empty placeholder.
    jira_issue_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # DWB-363: epic this issue belongs to. jira_epic_key sourced from
    # _extract_epic_key (parent.key when parent is an Epic; falls back
    # to the legacy customfield). jira_epic_name resolved in a SINGLE
    # batched call per sync (jira_sync collects unique epic keys, fetches
    # their summaries, then writes the name onto each snapshot) so adding
    # the epic column doesn't introduce N+1 fetches. NULL for issues
    # with no epic context (stand-alone tasks; epics themselves).
    jira_epic_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    jira_epic_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # DWB-364: parent Jira key for subtasks only. Sourced from
    # issue.fields.parent.key but ONLY persisted when
    # issuetype.subtask == True (the authoritative Jira signal). Non-
    # subtask tickets keep NULL here - their parent linkage is already
    # surfaced via the Epic column (DWB-363) when relevant; showing it
    # again under Parent would be redundant. The list endpoint serves
    # NULL through to the UI for the '-' placeholder.
    jira_parent_key: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Per-row sync stamp (last time the sync job refreshed THIS snapshot).
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
