# Path: alembic/versions/d8df2f9cf815_add_force_handoff_md_gate.py
# File: d8df2f9cf815_add_force_handoff_md_gate.py
# Created: 2026-04-16
# Purpose: Add force_handoff_md boolean gate column to projects table (default True)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: N/A (DDL migration)
# Data Out: N/A (DDL migration)
# Last Modified: 2026-04-16

"""add force_handoff_md gate

Revision ID: d8df2f9cf815
Revises: 3769113c20b0
Create Date: 2026-04-16 12:14:19.123666

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8df2f9cf815'
down_revision: Union[str, None] = '3769113c20b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('force_handoff_md', sa.Boolean(), nullable=False, server_default=sa.text('1')))
    # Set existing rows to True
    op.execute("UPDATE projects SET force_handoff_md = 1")


def downgrade() -> None:
    op.drop_column('projects', 'force_handoff_md')
