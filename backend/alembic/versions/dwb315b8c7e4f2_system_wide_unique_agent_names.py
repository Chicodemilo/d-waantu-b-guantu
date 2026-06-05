# Path: alembic/versions/dwb315b8c7e4f2_system_wide_unique_agent_names.py
# File: dwb315b8c7e4f2_system_wide_unique_agent_names.py
# Created: 2026-06-05
# Purpose: Rename colliding agents to system-unique form; drop UNIQUE(project_id,name); add UNIQUE(name)
# Caller: alembic upgrade head
# Callees: alembic.op, agents table, projects table
# Data In: existing agents rows + project prefixes
# Data Out: renamed agents.name values + new UNIQUE(name) constraint
# Last Modified: 2026-06-05

"""system-wide unique agent names (DWB-315)

Revision ID: dwb315b8c7e4f2
Revises: dwb308a4f2e91b
Create Date: 2026-06-05 15:55:00.000000

Goal: make `agents.name` globally unique. Fixed-role agents (Archie, Pam,
Mona) and any other cross-project name collisions get suffixed with
`_<PROJECT_PREFIX>`. Legacy rows with project_id IS NULL that still
collide get `_legacy_<id>` so we preserve the row + its FK history
without violating the new constraint.

Rename rules:
  - project_id IS NOT NULL  → name = name + '_' + project.prefix
  - project_id IS NULL      → name = name + '_legacy_' + id
  - "Mona" is renamed unconditionally per spec (even with only one row)

After the renames the new UNIQUE(name) constraint is enforceable.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb315b8c7e4f2"
down_revision: Union[str, None] = "dwb308a4f2e91b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Find every name with more than one agent — these are the collisions
    #    that must be disambiguated before UNIQUE(name) can land.
    colliding = {
        r.name
        for r in bind.execute(
            sa.text(
                "SELECT name FROM agents GROUP BY name HAVING COUNT(*) > 1"
            )
        ).fetchall()
    }
    # Spec mandate: rename Mona even if it has only one row, since it's a
    # fixed-role PM name that will collide as soon as another project adds
    # a Mona. Same intent for Archie/Pam — those are already in `colliding`
    # via the data audit, but adding them defensively is cheap.
    colliding.update({"Mona", "Archie", "Pam"})

    # 2. Walk every agent row. For colliding names, compute a unique name
    #    based on whether the row has a project (suffix with prefix) or is
    #    legacy (suffix with `_legacy_<id>`). All other rows untouched.
    rows = bind.execute(
        sa.text(
            "SELECT a.id, a.name, a.project_id, p.prefix "
            "FROM agents a LEFT JOIN projects p ON p.id = a.project_id"
        )
    ).fetchall()

    for row in rows:
        if row.name not in colliding:
            continue
        if row.project_id is not None and row.prefix:
            new_name = f"{row.name}_{row.prefix}"
        else:
            new_name = f"{row.name}_legacy_{row.id}"
        # Idempotency guard — if a previous partial run already suffixed
        # this row, don't double-suffix.
        if new_name == row.name:
            continue
        bind.execute(
            sa.text("UPDATE agents SET name = :n WHERE id = :i"),
            {"n": new_name, "i": row.id},
        )

    # 3. Replace the constraint. The old UNIQUE(project_id, name) becomes
    #    UNIQUE(name) — global uniqueness across all rows.
    op.drop_constraint("uq_agents_project_name", "agents", type_="unique")
    op.create_unique_constraint("uq_agents_name", "agents", ["name"])


def downgrade() -> None:
    # Schema-only revert. We don't un-suffix names — restore from backup if
    # you need the prior names, since the rename is data + the old constraint
    # would collide on the restored names if any project has multiple agents
    # with the same role-name. Same approach DWB-287 took for its downgrade.
    op.drop_constraint("uq_agents_name", "agents", type_="unique")
    op.create_unique_constraint(
        "uq_agents_project_name", "agents", ["project_id", "name"]
    )
