"""add user_sent_at to alert

Revision ID: 5c7f65bb1f5f
Revises: 1a44442800f6
Create Date: 2026-04-17 09:24:47.158298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c7f65bb1f5f'
down_revision: Union[str, None] = '1a44442800f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alerts', sa.Column('user_sent_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('alerts', 'user_sent_at')
