"""change agent role from enum to varchar

Revision ID: a45e9ef19f24
Revises: 82531ae5bbcc
Create Date: 2026-03-27 14:51:05.405612

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a45e9ef19f24'
down_revision: Union[str, None] = '82531ae5bbcc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "agents",
        "role",
        existing_type=sa.Enum("team_lead", "pm", "developer", "reviewer", "specialist", name="agentrole"),
        type_=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "agents",
        "role",
        existing_type=sa.String(100),
        type_=sa.Enum("team_lead", "pm", "developer", "reviewer", "specialist", name="agentrole"),
        existing_nullable=False,
    )
