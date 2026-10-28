"""Add `context_free` to agent_memories: the author's scope-free declaration.

Revision ID: dwb704a1b2c3
Revises: dwb695a1b2c3
Create Date: 2026-10-28

WHAT THIS COLUMN IS

The author's explicit statement that a lesson is bound to no single piece of
work. It is read by `memory_scan.scan_context`, which returns the new
`declared_broad` verdict for a row carrying it.

WHY A COLUMN RATHER THAN INFERRING IT FROM A NULL context_key

Because those are different facts and the whole cost of this area has come from
conflating them. A NULL `context_key` means no scope was ever RECORDED, which
is a data gap. This flag means a human DECIDED there is no scope, which is a
judgement. On 2026-10-06 one branch could not tell "I looked and found nothing"
from "this scope is eternal" and classified 381 of 455 scars as the latter,
promoting them into CORE - the tier only a human may grant. The repair was to
stop manufacturing a positive claim from an absence; this column is what lets
an author make that claim directly instead.

WHY NOT NULL WITH A False DEFAULT

A nullable boolean would reintroduce the same ambiguity one level down: NULL
would mean "no declaration", False would mean "declared not broad", and nothing
in the system distinguishes those. Every row that predates this column
genuinely carries no declaration, and False says exactly that.

BACKFILL

`server_default` covers existing rows at DDL time, and the explicit UPDATE
below is belt and braces for any row an in-flight transaction inserts between
the ADD COLUMN and the end of this migration. Both are required by the project
migration rules for a NOT NULL column on a populated table; `agent_memories`
holds ~1200 rows across three human_memory projects.

WHAT THIS MIGRATION DOES NOT DO

It does not set the flag on any existing row. The 424 rows carrying heading-path
context keys are not scope-free declarations - nobody declared anything about
them - and marking them would be inventing a judgement on an author's behalf,
which is the same defect this column exists to end. Repairing those rows is
tracked separately (DWB-705).
"""

import sqlalchemy as sa
from alembic import op

revision = "dwb704a1b2c3"
down_revision = "dwb695a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_memories",
        sa.Column(
            "context_free",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.execute("UPDATE agent_memories SET context_free = 0 WHERE context_free IS NULL")


def downgrade() -> None:
    op.drop_column("agent_memories", "context_free")
