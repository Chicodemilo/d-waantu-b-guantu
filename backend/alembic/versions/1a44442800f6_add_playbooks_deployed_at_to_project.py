"""add playbooks_deployed_at to project

Revision ID: 1a44442800f6
Revises: d8df2f9cf815
Create Date: 2026-04-17 08:13:37.780170

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1a44442800f6'
down_revision: Union[str, None] = 'd8df2f9cf815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('playbooks_deployed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'playbooks_deployed_at')
