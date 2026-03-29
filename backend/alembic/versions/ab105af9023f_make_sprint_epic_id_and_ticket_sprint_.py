"""make sprint epic_id and ticket sprint_id not null

Revision ID: ab105af9023f
Revises: 6e5f7de537ff
Create Date: 2026-03-27 16:14:22.392955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab105af9023f'
down_revision: Union[str, None] = '6e5f7de537ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("sprints", "epic_id",
                     existing_type=sa.BigInteger(),
                     nullable=False)
    op.alter_column("tickets", "sprint_id",
                     existing_type=sa.BigInteger(),
                     nullable=False)


def downgrade() -> None:
    op.alter_column("tickets", "sprint_id",
                     existing_type=sa.BigInteger(),
                     nullable=True)
    op.alter_column("sprints", "epic_id",
                     existing_type=sa.BigInteger(),
                     nullable=True)
