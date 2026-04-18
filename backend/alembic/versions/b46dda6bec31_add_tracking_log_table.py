"""add tracking_log table

Revision ID: b46dda6bec31
Revises: fba7d0af6706
Create Date: 2026-03-30 07:26:30.403944

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b46dda6bec31'
down_revision: Union[str, None] = 'fba7d0af6706'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tracking_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('ticket_id', sa.BigInteger(), nullable=True),
        sa.Column('agent_id', sa.BigInteger(), nullable=False),
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('sprint_id', sa.BigInteger(), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('timestamp', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['sprint_id'], ['sprints.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tracking_log_ticket_id'), 'tracking_log', ['ticket_id'], unique=False)
    op.create_index(op.f('ix_tracking_log_agent_id'), 'tracking_log', ['agent_id'], unique=False)
    op.create_index(op.f('ix_tracking_log_project_id'), 'tracking_log', ['project_id'], unique=False)
    op.create_index(op.f('ix_tracking_log_sprint_id'), 'tracking_log', ['sprint_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tracking_log_sprint_id'), table_name='tracking_log')
    op.drop_index(op.f('ix_tracking_log_project_id'), table_name='tracking_log')
    op.drop_index(op.f('ix_tracking_log_agent_id'), table_name='tracking_log')
    op.drop_index(op.f('ix_tracking_log_ticket_id'), table_name='tracking_log')
    op.drop_table('tracking_log')
