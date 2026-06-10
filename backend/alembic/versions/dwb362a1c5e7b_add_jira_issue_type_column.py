# Path: alembic/versions/dwb362a1c5e7b_add_jira_issue_type_column.py
# File: dwb362a1c5e7b_add_jira_issue_type_column.py
# Created: 2026-06-10
# Purpose: Add jira_ticket_snapshots.jira_issue_type column (DWB-362)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing jira_ticket_snapshots table
# Data Out: jira_issue_type VARCHAR(40) NULL column added
# Last Modified: 2026-06-10

"""DWB-362: add jira_issue_type column to jira_ticket_snapshots

Revision ID: dwb362a1c5e7b
Revises: dwb342f8b9c10
Create Date: 2026-06-10 15:50:00.000000

Hand-written per project rule.

DWB-362 introduces an 11th column on the unified Jira table showing the
Jira issue type (Task / Story / Bug / Sub-task / Epic / etc.). The
normalizer already extracted ``issue_type`` for the existing rollup
work; this migration adds the storage column on the snapshot cache and
the next sync run will populate it.

VARCHAR(40) is well over the longest standard Jira issue type name
(``Sub-task`` is 8 chars; custom types are usually short). Nullable so
pre-existing rows that haven't been re-synced still satisfy the schema.

Backfill: none. The list endpoint serves NULL through to the UI; once
the next sync runs, rows update naturally.

Downgrade: drop the column.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb362a1c5e7b"
down_revision: Union[str, None] = "dwb342f8b9c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jira_ticket_snapshots",
        sa.Column("jira_issue_type", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jira_ticket_snapshots", "jira_issue_type")
