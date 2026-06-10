# Path: alembic/versions/dwb371b2e8f5a_add_client_logs_table.py
# File: dwb371b2e8f5a_add_client_logs_table.py
# Created: 2026-06-10
# Purpose: Hand-written migration creating the client_logs table for frontend telemetry feed (DWB-371)
# Caller: alembic
# Callees: alembic.op, client_logs table
# Data In: previous schema state (head: dwb364c3e7a9d)
# Data Out: client_logs table with retention-friendly indexes
# Last Modified: 2026-06-10

"""add client_logs table (DWB-371)

Hand-written per the project rules note: autogenerate fabricates spurious
drop_index ops on error_logs, so we write migrations by hand for any
table near it. Schema mirrors app/models/client_log.py.

Indexes: created_at (retention trim + GET ordering), level / category /
route (the GET filters). source is low-cardinality, no index.

Revision ID: dwb371b2e8f5a
Revises: dwb364c3e7a9d
Create Date: 2026-06-10 17:50:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb371b2e8f5a"
down_revision: Union[str, None] = "dwb364c3e7a9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "client_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="frontend",
        ),
        sa.Column(
            "level",
            sa.Enum("debug", "info", "warn", "error", name="clientloglevel"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("route", sa.String(500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_logs_created_at", "client_logs", ["created_at"]
    )
    op.create_index("ix_client_logs_level", "client_logs", ["level"])
    op.create_index("ix_client_logs_category", "client_logs", ["category"])
    op.create_index("ix_client_logs_route", "client_logs", ["route"])


def downgrade() -> None:
    op.drop_index("ix_client_logs_route", "client_logs")
    op.drop_index("ix_client_logs_category", "client_logs")
    op.drop_index("ix_client_logs_level", "client_logs")
    op.drop_index("ix_client_logs_created_at", "client_logs")
    op.drop_table("client_logs")
