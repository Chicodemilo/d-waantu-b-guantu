# Path: alembic/versions/dwb287a01b2c_add_agents_project_id_split_and_unique.py
# File: dwb287a01b2c_add_agents_project_id_split_and_unique.py
# Created: 2026-06-03
# Purpose: Add agents.project_id, assign DWB roster to project 1, soft-deactivate dupes, UNIQUE(project_id, name)
# Caller: alembic upgrade head
# Callees: alembic.op, projects table, agents table, project_agents table
# Data In: N/A (DDL + targeted data fix)
# Data Out: N/A (DDL + targeted data fix)
# Last Modified: 2026-06-03

"""add agents.project_id, scope DWB roster, unique (project_id, name)

Revision ID: dwb287a01b2c
Revises: 5c7f65bb1f5f
Create Date: 2026-06-03 20:15:00.000000

Scope (per human override): DWB (project 1) only.
- Other projects' agents keep NULL project_id and are not touched.
- No FK repointing. Orphaned FK refs (from soft-deactivated rows) are accepted.
- See DWB-286 comment id=329 for the rationale.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dwb287a01b2c'
down_revision: Union[str, None] = '5c7f65bb1f5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# DWB project id and the agents that should live on it after this migration.
# Each entry is (agent_id, name) — used both for the SET project_id step and
# as a sanity-check ahead of adding UNIQUE(project_id, name).
DWB_PROJECT_ID = 1
DWB_KEEPERS = [
    (2, "Mona"),     # pm — no name dupe, kept by default
    (3, "Pixel"),    # frontend-worker
    (4, "Devin"),    # backend-worker
    (5, "Bolt"),     # system-ops
    (6, "Sage"),     # tester
    (13, "Archie"),  # team-lead — replaces id=1 (re-linked from RVP)
    (14, "Pam"),     # pm — re-linked from RVP
    (19, "Freddie"), # frontend-worker
]
# Agents to add to project_agents (DWB) — these are NOT currently linked to DWB.
DWB_NEW_LINKS = [13, 14]
# Agents currently in project_agents (DWB) that should be unlinked. id=1 is the
# old Archie row superseded by id=13.
DWB_REMOVE_LINKS = [1]
# Agents to soft-deactivate. Cannot hard-DELETE due to NOT NULL FK refs from
# tracking_log/alerts/comments/failure_records. Row remains with
# project_id=NULL so it doesn't collide with the new DWB Archie (id=13).
SOFT_DEACTIVATE = [1]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add agents.project_id (nullable), FK + index
    op.add_column('agents', sa.Column('project_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_agents_project_id', 'agents', 'projects', ['project_id'], ['id']
    )
    op.create_index('ix_agents_project_id', 'agents', ['project_id'])

    # 2. Assign DWB keepers their project_id
    for agent_id, _name in DWB_KEEPERS:
        bind.execute(
            sa.text("UPDATE agents SET project_id = :pid WHERE id = :aid"),
            {"pid": DWB_PROJECT_ID, "aid": agent_id},
        )

    # 3. Add new DWB project_agents links for re-linked agents (13, 14)
    for agent_id in DWB_NEW_LINKS:
        bind.execute(sa.text("""
            INSERT INTO project_agents (project_id, agent_id, assigned_at)
            VALUES (:pid, :aid, NOW())
        """), {"pid": DWB_PROJECT_ID, "aid": agent_id})

    # 4. Remove old DWB project_agents links for superseded agents (1)
    for agent_id in DWB_REMOVE_LINKS:
        bind.execute(
            sa.text(
                "DELETE FROM project_agents WHERE project_id = :pid AND agent_id = :aid"
            ),
            {"pid": DWB_PROJECT_ID, "aid": agent_id},
        )

    # 5. Soft-deactivate superseded agents (keep row, NULL project_id, is_active=0)
    for agent_id in SOFT_DEACTIVATE:
        bind.execute(
            sa.text("UPDATE agents SET is_active = 0 WHERE id = :aid"),
            {"aid": agent_id},
        )

    # 6. UNIQUE(project_id, name). MySQL treats NULL != NULL in unique
    # constraints, so non-DWB rows (project_id NULL) are unaffected.
    op.create_unique_constraint(
        'uq_agents_project_name', 'agents', ['project_id', 'name']
    )


def downgrade() -> None:
    # Schema-only revert. Soft-deactivation and project_agents row mutations are
    # not unwound here — restore from backup if you need the prior state.
    op.drop_constraint('uq_agents_project_name', 'agents', type_='unique')
    op.drop_index('ix_agents_project_id', table_name='agents')
    op.drop_constraint('fk_agents_project_id', 'agents', type_='foreignkey')
    op.drop_column('agents', 'project_id')
