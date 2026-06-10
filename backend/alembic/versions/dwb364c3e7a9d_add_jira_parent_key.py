# Path: alembic/versions/dwb364c3e7a9d_add_jira_parent_key.py
# File: dwb364c3e7a9d_add_jira_parent_key.py
# Created: 2026-06-10
# Purpose: Add jira_parent_key column to jira_ticket_snapshots (DWB-364)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing jira_ticket_snapshots table
# Data Out: jira_parent_key VARCHAR(40) NULL column added
# Last Modified: 2026-06-10

"""DWB-364: add jira_parent_key to jira_ticket_snapshots

Revision ID: dwb364c3e7a9d
Revises: dwb363b2d6f8c
Create Date: 2026-06-10 16:20:00.000000

Hand-written per project rule.

DWB-364 adds a Parent column to the unified Jira table, populated only
for subtasks (where Jira's issuetype.subtask boolean is True). Non-
subtask rows leave the column NULL.

Column width 40 matches the other Jira key columns (jira_epic_key,
jira_issue_key). Nullable so pre-existing rows + non-subtask rows are
unconstrained.

Backfill: none. Next manual sync populates jira_parent_key on subtask
rows; non-subtask rows stay NULL by design.

Downgrade: drop the column.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb364c3e7a9d"
down_revision: Union[str, None] = "dwb363b2d6f8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jira_ticket_snapshots",
        sa.Column("jira_parent_key", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jira_ticket_snapshots", "jira_parent_key")
