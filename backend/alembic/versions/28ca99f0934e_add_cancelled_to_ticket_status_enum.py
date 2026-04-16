# Path: alembic/versions/28ca99f0934e_add_cancelled_to_ticket_status_enum.py
# File: 28ca99f0934e_add_cancelled_to_ticket_status_enum.py
# Created: 2026-04-16
# Purpose: Add 'cancelled' value to tickets.status ENUM column
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: N/A (DDL migration)
# Data Out: N/A (DDL migration)
# Last Modified: 2026-04-16

"""add cancelled to ticket status enum

Revision ID: 28ca99f0934e
Revises: 85a791a9f79d
Create Date: 2026-04-16 09:42:07.528189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28ca99f0934e'
down_revision: Union[str, None] = '85a791a9f79d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tickets MODIFY COLUMN status "
        "ENUM('backlog','todo','in_progress','in_review','done','cancelled') "
        "NOT NULL DEFAULT 'backlog'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE tickets MODIFY COLUMN status "
        "ENUM('backlog','todo','in_progress','in_review','done') "
        "NOT NULL DEFAULT 'backlog'"
    )
