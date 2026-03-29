"""add test_results table

Revision ID: 7c2db5e29c01
Revises: 001_initial_schema
Create Date: 2026-03-27 10:18:33.792054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2db5e29c01'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'test_results',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('run_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('suite', sa.String(length=100), nullable=False),
        sa.Column('total_tests', sa.Integer(), nullable=False),
        sa.Column('passed', sa.Integer(), nullable=False),
        sa.Column('failed', sa.Integer(), nullable=False),
        sa.Column('skipped', sa.Integer(), nullable=False),
        sa.Column('duration_seconds', sa.Float(), nullable=False),
        sa.Column('status', sa.Enum('passed', 'failed', 'error', name='teststatus'), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('triggered_by', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_test_results_project_id'), 'test_results', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_test_results_project_id'), table_name='test_results')
    op.drop_table('test_results')
