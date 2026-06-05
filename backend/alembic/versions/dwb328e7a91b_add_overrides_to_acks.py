# Path: alembic/versions/dwb328e7a91b_add_overrides_to_acks.py
# File: dwb328e7a91b_add_overrides_to_acks.py
# Created: 2026-06-05
# Purpose: Add overrides JSON column to agent_consolidation_acks (DWB-328 gate teeth)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: N/A (DDL migration)
# Data Out: N/A (DDL migration)
# Last Modified: 2026-06-05

"""add_overrides_to_agent_consolidation_acks

Revision ID: dwb328e7a91b
Revises: dwb321a5e9c2
Create Date: 2026-06-05

DWB-328: gate teeth. Acks must include per-file override reasons when the
agent's owned files are over ceiling. Stores the override map alongside the
ack so the TL can audit who justified what.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dwb328e7a91b'
down_revision: Union[str, None] = 'dwb321a5e9c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'agent_consolidation_acks',
        sa.Column('overrides', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('agent_consolidation_acks', 'overrides')
