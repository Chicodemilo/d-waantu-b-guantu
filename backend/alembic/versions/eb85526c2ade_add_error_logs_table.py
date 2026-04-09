"""add error_logs table

Revision ID: eb85526c2ade
Revises: beb4ba35f9b0
Create Date: 2026-04-09 14:20:23.396191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb85526c2ade'
down_revision: Union[str, None] = 'beb4ba35f9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'error_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.BigInteger(), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agent_id', sa.BigInteger(), sa.ForeignKey('agents.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source', sa.Enum('backend', 'frontend', 'hook', name='errorsource'), nullable=False),
        sa.Column('endpoint', sa.String(500), nullable=True),
        sa.Column('error_type', sa.String(255), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('function_name', sa.String(255), nullable=True),
        sa.Column('line_number', sa.Integer(), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_error_logs_project_id', 'error_logs', ['project_id'])
    op.create_index('ix_error_logs_agent_id', 'error_logs', ['agent_id'])
    op.create_index('ix_error_logs_source', 'error_logs', ['source'])
    op.create_index('ix_error_logs_created_at', 'error_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_error_logs_created_at', 'error_logs')
    op.drop_index('ix_error_logs_source', 'error_logs')
    op.drop_index('ix_error_logs_agent_id', 'error_logs')
    op.drop_index('ix_error_logs_project_id', 'error_logs')
    op.drop_table('error_logs')
