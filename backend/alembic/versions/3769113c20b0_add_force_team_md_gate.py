# Path: alembic/versions/3769113c20b0_add_force_team_md_gate.py
# File: 3769113c20b0_add_force_team_md_gate.py
# Created: 2026-04-16
# Purpose: Add force_team_md boolean gate column to projects table (default True)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: N/A (DDL migration)
# Data Out: N/A (DDL migration)
# Last Modified: 2026-04-16

"""add force_team_md gate

Revision ID: 3769113c20b0
Revises: 28ca99f0934e
Create Date: 2026-04-16 10:49:06.121584

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3769113c20b0'
down_revision: Union[str, None] = '28ca99f0934e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('force_team_md', sa.Boolean(), nullable=False, server_default=sa.text('1')))
    # Set existing rows to True
    op.execute("UPDATE projects SET force_team_md = 1")


def downgrade() -> None:
    op.drop_column('projects', 'force_team_md')
