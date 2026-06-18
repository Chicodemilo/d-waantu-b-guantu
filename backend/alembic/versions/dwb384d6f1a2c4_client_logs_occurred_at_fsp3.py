# Path: alembic/versions/dwb384d6f1a2c4_client_logs_occurred_at_fsp3.py
# File: dwb384d6f1a2c4_client_logs_occurred_at_fsp3.py
# Created: 2026-06-12
# Purpose: Hand-written migration widening client_logs.occurred_at to DATETIME(3) so same-second emits sort deterministically (DWB-384)
# Caller: alembic
# Callees: alembic.op, client_logs.occurred_at column
# Data In: previous schema state (down_revision: dwb382c5e9f0b3)
# Data Out: client_logs.occurred_at is DATETIME(3) on MySQL
# Last Modified: 2026-06-12

"""client_logs.occurred_at -> DATETIME(fsp=3) (DWB-384)

Plain DATETIME on MySQL has no fractional-second precision, so two
client_logs rows that share a wall-clock second sort randomly. Widening
to DATETIME(3) preserves millisecond ordering. Schema-only - existing
rows retain their second-truncated values, which is intentional per the
ticket (no data backfill).

Revision ID: dwb384d6f1a2c4
Revises: dwb382c5e9f0b3
Create Date: 2026-06-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "dwb384d6f1a2c4"
down_revision: Union[str, None] = "dwb382c5e9f0b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "client_logs",
        "occurred_at",
        existing_type=sa.DateTime(),
        type_=mysql.DATETIME(fsp=3),
        existing_nullable=False,
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "client_logs",
        "occurred_at",
        existing_type=mysql.DATETIME(fsp=3),
        type_=sa.DateTime(),
        existing_nullable=False,
        nullable=False,
    )
