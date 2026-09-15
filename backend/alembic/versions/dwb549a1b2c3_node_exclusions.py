# Path: alembic/versions/dwb549a1b2c3_node_exclusions.py
# File: dwb549a1b2c3_node_exclusions.py
# Created: 2026-09-15 (DWB-549)
# Purpose: Per-project node-scan exclusions: the node_exclusions table plus the
#          projects.node_exclusions_seeded flag that makes deleting a seeded
#          default permanent.
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing schema at dwb537a1b2c3
# Data Out: node_exclusions table; projects.node_exclusions_seeded TINYINT(1)
# Last Modified: 2026-09-15 (DWB-549)

"""per-project node scan exclusions (DWB-549)

Revision ID: dwb549a1b2c3
Revises: dwb537a1b2c3
Create Date: 2026-09-15 00:00:00.000000

Hand-written per project rules (autogenerate emits spurious drop_index ops on
error_logs, and a NOT NULL column added to a populated table needs an explicit
server_default plus a backfill).

The seeded flag is deliberately NOT inferred from "this project has zero
exclusion rows". A user who deletes every seeded default must keep an empty
list; inferring would re-seed them on the next read and silently undo the
deletion. Existing rows backfill to 0 so every project seeds once, on first use.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dwb549a1b2c3"
down_revision: Union[str, Sequence[str], None] = "dwb537a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "node_exclusions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("pattern", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "pattern", name="uq_node_exclusions_project_pattern"
        ),
    )
    op.create_index(
        "ix_node_exclusions_project_id", "node_exclusions", ["project_id"]
    )

    op.add_column(
        "projects",
        sa.Column(
            "node_exclusions_seeded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Explicit backfill: every existing project is "not yet seeded", so each one
    # picks up the shipped defaults once, on its first use of the list.
    op.execute("UPDATE projects SET node_exclusions_seeded = 0")


def downgrade() -> None:
    op.drop_column("projects", "node_exclusions_seeded")
    op.drop_index("ix_node_exclusions_project_id", table_name="node_exclusions")
    op.drop_table("node_exclusions")
