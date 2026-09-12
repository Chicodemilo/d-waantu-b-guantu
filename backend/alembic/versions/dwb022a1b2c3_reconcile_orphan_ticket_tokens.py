# Path: alembic/versions/dwb022a1b2c3_reconcile_orphan_ticket_tokens.py
# File: dwb022a1b2c3_reconcile_orphan_ticket_tokens.py
# Created: 2026-08-12 (DWB-022)
# Purpose: One-time backfill of tracking_log token_report events for tickets
#          whose tokens_used was written without a backing ledger row (the
#          pre-fix phantom: token_source 'unknown'/NULL, no token_report event).
# Caller: alembic upgrade head
# Callees: app.services.tracking.reconcile_orphan_ticket_tokens
# Data In: existing schema at dwb028a1b2c3
# Data Out: backfilled tracking_log token_report rows + tickets.token_source='reconciled'
# Last Modified: 2026-08-12 (DWB-022)

"""reconcile orphan ticket tokens (DWB-022)

Revision ID: dwb022a1b2c3
Revises: dwb028a1b2c3
Create Date: 2026-08-12 00:00:00.000000

Historical backfill for the phantom-token bug. Before DWB-022, POST
/api/tickets/:id/tokens wrote ticket.tokens_used with token_source='unknown' and
NO tracking_log event, so per-agent/per-ticket rollups (which read the ledger)
reported 0 for real work (e.g. Barry_DWB's ~198k across DWB-013/014/016). The
service fix makes every new increment emit a ledger event; this migration
reconciles the rows already on disk.

It runs the canonical reconcile SERVICE function (single source of truth, unit-
tested) rather than duplicating the query as raw SQL. Idempotent: a ticket that
already has a token_report event is skipped, so re-running never double-counts.
Schema-only downgrade is a no-op - the backfilled ledger rows are real data, not
structure, and deleting them would re-open the very gap this closes.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

from app.services.tracking import reconcile_orphan_ticket_tokens


revision: str = "dwb022a1b2c3"
down_revision: Union[str, None] = "dwb028a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    n = reconcile_orphan_ticket_tokens(session)
    print(f"DWB-022: reconciled {n} orphan-token ticket(s) into tracking_log")


def downgrade() -> None:
    # No-op: the backfilled token_report rows are real attribution data, not
    # schema. Removing them would recreate the phantom (tokens_used with no
    # ledger). Leave them in place.
    pass
