# Path: alembic/versions/dwb288f1ed3a4_add_failed_hooks_table.py
# File: dwb288f1ed3a4_add_failed_hooks_table.py
# Created: 2026-06-03
# Purpose: Create failed_hooks table — records of hook endpoint failures
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: N/A (DDL migration)
# Data Out: N/A (DDL migration)
# Last Modified: 2026-06-03

"""add failed_hooks table

Revision ID: dwb288f1ed3a4
Revises: dwb287a01b2c
Create Date: 2026-06-03 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dwb288f1ed3a4'
down_revision: Union[str, None] = 'dwb287a01b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'failed_hooks',
        sa.Column('id', sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column('fired_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('hook_event', sa.String(length=50), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('payload_snippet', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_failed_hooks_fired_at', 'failed_hooks', ['fired_at'])
    op.create_index('ix_failed_hooks_hook_event', 'failed_hooks', ['hook_event'])


def downgrade() -> None:
    op.drop_index('ix_failed_hooks_hook_event', table_name='failed_hooks')
    op.drop_index('ix_failed_hooks_fired_at', table_name='failed_hooks')
    op.drop_table('failed_hooks')
