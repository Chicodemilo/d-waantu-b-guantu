# Path: alembic/versions/ff83d04f7cfa_add_force_consolidation_to_projects.py
# File: ff83d04f7cfa_add_force_consolidation_to_projects.py
# Created: 2026-06-04
# Purpose: Add force_consolidation column to projects + create agent_consolidation_acks table
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: N/A (DDL migration)
# Data Out: N/A (DDL migration)
# Last Modified: 2026-06-04

"""add_force_consolidation_to_projects

Revision ID: ff83d04f7cfa
Revises: dwb288f1ed3a4
Create Date: 2026-06-04 14:00:08.084781

Backs the consolidation gate. Adds a per-project toggle and a per-agent /
per-sprint ack table that the sprint-close path checks before closing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ff83d04f7cfa'
down_revision: Union[str, None] = 'dwb288f1ed3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New gate toggle. server_default='0' so existing rows backfill cleanly
    # under MySQL — Boolean is TINYINT(1) under the hood.
    op.add_column(
        'projects',
        sa.Column(
            'force_consolidation',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )

    op.create_table(
        'agent_consolidation_acks',
        sa.Column('id', sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column('agent_id', sa.BigInteger(), nullable=False),
        sa.Column('sprint_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'acked_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.ForeignKeyConstraint(['sprint_id'], ['sprints.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'sprint_id', name='uq_consolidation_agent_sprint'),
    )
    op.create_index(
        'ix_agent_consolidation_acks_agent_id',
        'agent_consolidation_acks',
        ['agent_id'],
    )
    op.create_index(
        'ix_agent_consolidation_acks_sprint_id',
        'agent_consolidation_acks',
        ['sprint_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_agent_consolidation_acks_sprint_id', table_name='agent_consolidation_acks')
    op.drop_index('ix_agent_consolidation_acks_agent_id', table_name='agent_consolidation_acks')
    op.drop_table('agent_consolidation_acks')
    op.drop_column('projects', 'force_consolidation')
