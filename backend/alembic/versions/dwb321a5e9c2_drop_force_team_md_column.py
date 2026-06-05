# Path: alembic/versions/dwb321a5e9c2_drop_force_team_md_column.py
# File: dwb321a5e9c2_drop_force_team_md_column.py
# Created: 2026-06-05
# Purpose: Drop force_team_md column from projects (DWB-321 — gate retired)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: N/A (DDL migration)
# Data Out: N/A (DDL migration)
# Last Modified: 2026-06-05

"""drop_force_team_md_column

Revision ID: dwb321a5e9c2
Revises: dwb315b8c7e4f2
Create Date: 2026-06-05

DWB-321: TEAM.md gate fully retired. Roster is DB-authoritative via
`GET /api/projects/{id}/team` (DWB-313). Drop the `force_team_md` column —
no replacement, no shim.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dwb321a5e9c2'
down_revision: Union[str, None] = 'dwb315b8c7e4f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('projects', 'force_team_md')


def downgrade() -> None:
    op.add_column(
        'projects',
        sa.Column(
            'force_team_md',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('1'),
        ),
    )
