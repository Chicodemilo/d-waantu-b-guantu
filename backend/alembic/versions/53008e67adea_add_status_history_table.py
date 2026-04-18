"""add status_history table

Revision ID: 53008e67adea
Revises: f992516a6b1c
Create Date: 2026-03-28 17:21:54.153638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53008e67adea'
down_revision: Union[str, None] = 'f992516a6b1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'status_history',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('ticket_id', sa.BigInteger(), nullable=False),
        sa.Column('old_status', sa.String(length=50), nullable=False),
        sa.Column('new_status', sa.String(length=50), nullable=False),
        sa.Column('changed_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('changed_by_agent_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id']),
        sa.ForeignKeyConstraint(['changed_by_agent_id'], ['agents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_status_history_ticket_id'), 'status_history', ['ticket_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_status_history_ticket_id'), table_name='status_history')
    op.drop_table('status_history')
