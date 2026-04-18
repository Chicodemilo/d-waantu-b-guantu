"""add failure_records table

Revision ID: f992516a6b1c
Revises: 2e12eb5a0b56
Create Date: 2026-03-28 12:33:05.004152

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f992516a6b1c'
down_revision: Union[str, None] = '2e12eb5a0b56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'failure_records',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('ticket_id', sa.BigInteger(), nullable=True),
        sa.Column('sprint_id', sa.BigInteger(), nullable=False),
        sa.Column('agent_id', sa.BigInteger(), nullable=False),
        sa.Column('logged_by_agent_id', sa.BigInteger(), nullable=False),
        sa.Column('failure_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False, server_default='medium'),
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('root_cause', sa.Text(), nullable=True),
        sa.Column('resolution', sa.Text(), nullable=True),
        sa.Column('resolved', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id']),
        sa.ForeignKeyConstraint(['sprint_id'], ['sprints.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.ForeignKeyConstraint(['logged_by_agent_id'], ['agents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_failure_records_project_id'), 'failure_records', ['project_id'], unique=False)
    op.create_index(op.f('ix_failure_records_ticket_id'), 'failure_records', ['ticket_id'], unique=False)
    op.create_index(op.f('ix_failure_records_sprint_id'), 'failure_records', ['sprint_id'], unique=False)
    op.create_index(op.f('ix_failure_records_agent_id'), 'failure_records', ['agent_id'], unique=False)
    op.create_index(op.f('ix_failure_records_logged_by_agent_id'), 'failure_records', ['logged_by_agent_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_failure_records_logged_by_agent_id'), table_name='failure_records')
    op.drop_index(op.f('ix_failure_records_agent_id'), table_name='failure_records')
    op.drop_index(op.f('ix_failure_records_sprint_id'), table_name='failure_records')
    op.drop_index(op.f('ix_failure_records_ticket_id'), table_name='failure_records')
    op.drop_index(op.f('ix_failure_records_project_id'), table_name='failure_records')
    op.drop_table('failure_records')
