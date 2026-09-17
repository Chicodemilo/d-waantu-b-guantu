"""DWB-581: ticket_source on hook_sessions

Revision ID: dwb581a1b2c3
Revises: dwb580a1b2c3
Create Date: 2026-09-17

Hand-written: autogenerate on this schema invents spurious drop_index ops on
error_logs (see .claude/project_rules_worker.md), and this is one nullable
column.

NO BACKFILL, and that is the design rather than an omission. Every existing row
stays NULL, which reads as "we do not know how this row got its ticket". That is
true: those rows were written before the distinction was recorded. Stamping a
value on them would manufacture exactly the confidence this column exists to
expose.
"""
from alembic import op
import sqlalchemy as sa

revision = "dwb581a1b2c3"
down_revision = "dwb580a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hook_sessions",
        sa.Column("ticket_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hook_sessions", "ticket_source")
