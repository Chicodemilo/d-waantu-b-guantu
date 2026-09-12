# Path: alembic/versions/dwb028a1b2c3_create_the_auditor_agent.py
# File: dwb028a1b2c3_create_the_auditor_agent.py
# Created: 2026-08-12 (DWB-028)
# Purpose: Seed the fixed 'The_Auditor' system agent so standards-audit writes
#          attribute to it in the activity feed + alerts (DWB-028).
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing schema at dwb017a1b2c3
# Data Out: one agents row (name='The_Auditor'), idempotent
# Last Modified: 2026-08-12 (DWB-028)

"""create The_Auditor system agent (DWB-028)

Revision ID: dwb028a1b2c3
Revises: dwb017a1b2c3
Create Date: 2026-08-12 00:00:00.000000

Hand-written data migration. Inserts the fixed 'The_Auditor' agent used to
attribute standards-audit alerts + activity-feed events (DWB-028). Global system
agent: project_id is NULL (agents.project_id is nullable, DWB-287). Idempotent -
skips the insert when a row with that (globally unique) name already exists, so
re-running or an already-seeded prod DB is a no-op.

STANDARDS_AUDIT_AGENT_ID can be set in .env to this row's id; when unset the
create service resolves the agent by name, so no post-migration wiring is
strictly required.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb028a1b2c3"
down_revision: Union[str, None] = "dwb017a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_AUDITOR_NAME = "The_Auditor"
_AUDITOR_ROLE = "auditor"
_AUDITOR_API_KEY = "system-the-auditor"


def upgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT id FROM agents WHERE name = :name"),
        {"name": _AUDITOR_NAME},
    ).first()
    if existing is None:
        conn.execute(
            sa.text(
                "INSERT INTO agents (name, role, api_key, is_active, project_id) "
                "VALUES (:name, :role, :api_key, 1, NULL)"
            ),
            {
                "name": _AUDITOR_NAME,
                "role": _AUDITOR_ROLE,
                "api_key": _AUDITOR_API_KEY,
            },
        )


def downgrade() -> None:
    # Best-effort: removes the seeded row. Fails loudly if it is referenced by
    # alerts/activity (FK) - reverse-apply those first if you must roll back.
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM agents WHERE name = :name AND api_key = :api_key"),
        {"name": _AUDITOR_NAME, "api_key": _AUDITOR_API_KEY},
    )
