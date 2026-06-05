# Path: alembic/versions/dwb305c7f1e2a_backfill_overhead_token_buckets.py
# File: dwb305c7f1e2a_backfill_overhead_token_buckets.py
# Created: 2026-06-05
# Purpose: Backfill projects.tl_overhead_tokens + pm_overhead_tokens from tracking_log
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing tracking_log + agents rows
# Data Out: rewritten per-role bucket totals on projects
# Last Modified: 2026-06-05

"""backfill overhead token buckets (DWB-305)

Revision ID: dwb305c7f1e2a
Revises: ff83d04f7cfa
Create Date: 2026-06-05 13:45:00.000000

The bucket-increment code in hook_tracking.py only landed on 2026-04-17
(commit eb3d66a). Every overhead_token_report row written before that
commit — plus a handful that drifted afterwards — leaves the cached
per-role buckets out of sync with the project_total computed from
tracking_log.

This migration recomputes tl_overhead_tokens and pm_overhead_tokens from
the authoritative tracking_log rows, restoring the invariant:

    project.tl_overhead_tokens + project.pm_overhead_tokens
        == SUM(tracking_log.tokens
               WHERE event_type='overhead_token_report'
                 AND project_id = project.id)

Classification mirrors tracking.log_overhead_tokens(): rows whose
agent has role='pm' land in pm_overhead_tokens; every other role
(including team-lead and any stray worker overhead) lands in
tl_overhead_tokens. The agent-id JOIN is LEFT so orphaned rows still
contribute to tl_overhead (defensive: never lose totals).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "dwb305c7f1e2a"
down_revision: Union[str, None] = "ff83d04f7cfa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rebuild pm_overhead_tokens from tracking_log.
    op.execute(
        """
        UPDATE projects p
        LEFT JOIN (
            SELECT tl.project_id, COALESCE(SUM(tl.tokens), 0) AS total
            FROM tracking_log tl
            JOIN agents a ON a.id = tl.agent_id
            WHERE tl.event_type = 'overhead_token_report'
              AND a.role = 'pm'
            GROUP BY tl.project_id
        ) pm ON pm.project_id = p.id
        SET p.pm_overhead_tokens = COALESCE(pm.total, 0)
        """
    )

    # Rebuild tl_overhead_tokens from tracking_log. Anything that isn't PM
    # (team-lead, NULL agent, stray worker overhead) goes here so the
    # invariant tl + pm == project_total.overhead_tokens always closes.
    op.execute(
        """
        UPDATE projects p
        LEFT JOIN (
            SELECT tl.project_id, COALESCE(SUM(tl.tokens), 0) AS total
            FROM tracking_log tl
            LEFT JOIN agents a ON a.id = tl.agent_id
            WHERE tl.event_type = 'overhead_token_report'
              AND (a.role IS NULL OR a.role <> 'pm')
            GROUP BY tl.project_id
        ) tl ON tl.project_id = p.id
        SET p.tl_overhead_tokens = COALESCE(tl.total, 0)
        """
    )


def downgrade() -> None:
    # Backfill is data-only; we don't restore the pre-backfill drift.
    # No-op downgrade is safe.
    pass
