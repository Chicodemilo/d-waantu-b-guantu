# Path: alembic/versions/dwb363b2d6f8c_add_jira_epic_columns.py
# File: dwb363b2d6f8c_add_jira_epic_columns.py
# Created: 2026-06-10
# Purpose: Add jira_epic_key + jira_epic_name columns to jira_ticket_snapshots (DWB-363)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing jira_ticket_snapshots table
# Data Out: jira_epic_key VARCHAR(40) NULL + jira_epic_name VARCHAR(255) NULL columns added
# Last Modified: 2026-06-10

"""DWB-363: add jira_epic_key + jira_epic_name to jira_ticket_snapshots

Revision ID: dwb363b2d6f8c
Revises: dwb362a1c5e7b
Create Date: 2026-06-10 16:10:00.000000

Hand-written per project rule.

DWB-363 introduces a 12th column on the unified Jira table showing the
Jira epic the issue belongs to. Two snapshot columns:

  - jira_epic_key   VARCHAR(40)  NULL  (e.g. "POR-5152")
  - jira_epic_name  VARCHAR(255) NULL  (e.g. "Gemini AI Claims/Fraud")

Width:
  - Jira keys are short (<= 20 chars in practice); 40 is generous.
  - Epic names follow Jira summary limits (~255 chars); we use 255 to
    match the existing jira_sprint_name + jira_assignee width.

Backfill: none. New columns default NULL on pre-DWB-363 rows; the next
manual sync populates them in a single batched epic-summary call (one
extra Jira fetch per sync, NOT one per issue - see jira_sync.run_sync).

Downgrade: drop both columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb363b2d6f8c"
down_revision: Union[str, None] = "dwb362a1c5e7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jira_ticket_snapshots",
        sa.Column("jira_epic_key", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "jira_ticket_snapshots",
        sa.Column("jira_epic_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jira_ticket_snapshots", "jira_epic_name")
    op.drop_column("jira_ticket_snapshots", "jira_epic_key")
