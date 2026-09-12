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


# --- idempotency / fresh-install helpers (DWB-481) -------------------------
# This migration was authored as a one-off data fixup against the DWB team's
# own production DB, where project 1 and agents 2..19 already existed. On a
# fresh install (`alembic upgrade head` from base) none of those rows exist,
# so the original INSERT into project_agents tripped a FK constraint. The
# guards below make every step a no-op when its target rows are absent, while
# preserving the exact original behavior where they are present. The DDL steps
# are guarded too so a partially-applied run can be re-run cleanly.

def _has_column(bind, table, column) -> bool:
    return bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar() > 0


def _has_index(bind, table, index) -> bool:
    return bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
    ), {"t": table, "i": index}).scalar() > 0


def _has_constraint(bind, table, name) -> bool:
    return bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.table_constraints "
        "WHERE table_schema = DATABASE() AND table_name = :t AND constraint_name = :n"
    ), {"t": table, "n": name}).scalar() > 0


def _exists(bind, table, value) -> bool:
    return bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE id = :v"), {"v": value}
    ).scalar() > 0


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add agents.project_id (nullable), FK + index (idempotent)
    if not _has_column(bind, 'agents', 'project_id'):
        op.add_column('agents', sa.Column('project_id', sa.BigInteger(), nullable=True))
    if not _has_constraint(bind, 'agents', 'fk_agents_project_id'):
        op.create_foreign_key(
            'fk_agents_project_id', 'agents', 'projects', ['project_id'], ['id']
        )
    if not _has_index(bind, 'agents', 'ix_agents_project_id'):
        op.create_index('ix_agents_project_id', 'agents', ['project_id'])

    # 2-5. Data fix is DWB-roster-specific (hardcoded agent IDs that map to
    # roles on the work-machine DB). Skip the entire block on any DB that
    # isn't the DWB work DB. Fingerprint: a project with prefix='DWB'.
    is_dwb_db = bind.execute(
        sa.text("SELECT 1 FROM projects WHERE prefix = 'DWB' LIMIT 1")
    ).first()

    if is_dwb_db:
        # 2. Assign DWB keepers their project_id
        for agent_id, _name in DWB_KEEPERS:
            bind.execute(
                sa.text("UPDATE agents SET project_id = :pid WHERE id = :aid"),
                {"pid": DWB_PROJECT_ID, "aid": agent_id},
            )

        # 3. Add new DWB project_agents links for re-linked agents (13, 14)
        #    Guard on both the agent existing and the link not already present.
        for agent_id in DWB_NEW_LINKS:
            if not _exists(bind, 'agents', agent_id):
                continue
            already = bind.execute(sa.text(
                "SELECT COUNT(*) FROM project_agents "
                "WHERE project_id = :pid AND agent_id = :aid"
            ), {"pid": DWB_PROJECT_ID, "aid": agent_id}).scalar()
            if not already:
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
            if _exists(bind, 'agents', agent_id):
                bind.execute(
                    sa.text("UPDATE agents SET is_active = 0 WHERE id = :aid"),
                    {"aid": agent_id},
                )

    # 6. UNIQUE(project_id, name). MySQL treats NULL != NULL in unique
    # constraints, so non-DWB rows (project_id NULL) are unaffected.
    if not _has_constraint(bind, 'agents', 'uq_agents_project_name'):
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
