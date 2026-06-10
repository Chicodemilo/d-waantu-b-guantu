# Path: alembic/versions/dwb353c9d4e1f_dismiss_dead_alerts.py
# File: dwb353c9d4e1f_dismiss_dead_alerts.py
# Created: 2026-06-10
# Purpose: Backfill scrub - dismiss any open "tokens-not-reported" and "Unattributed hook session" alerts; both classes are removed by DWB-353 (code paths deleted)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing alerts rows
# Data Out: rewritten alerts.status (open|acknowledged -> dismissed) for the two dead classes
# Last Modified: 2026-06-10

"""dismiss dead alert classes (DWB-353)

Revision ID: dwb353c9d4e1f
Revises: dwb346b8e2c91
Create Date: 2026-06-10 13:30:00.000000

DWB-353 removes two alert classes whose fire paths are now dead code:

  1. "Tokens not reported for <ticket_key>"
     Source: app/services/ticket.py - fired on every ticket close where
     ticket.tokens_used == 0. Made dead by the hook attribution layer
     (tokens land in tracking_log via hook_sessions; ticket.tokens_used
     stays at 0 for hook-attributed tickets). Was firing on every close.

  2. "Unattributed hook session: <session_id>"
     Source: app/services/hook_tracking.py::_create_unattributed_alert.
     Fired when a hook session had tokens but no agent attribution. The
     skip-ticket-overhead lane is by design - the user does not want
     Pam/TL paged on it. Worker-without-ticket tokens now flow into
     the ad_hoc bucket (DWB-353) instead.

This migration dismisses every existing open / acknowledged alert in
those two classes. We do NOT delete the rows so historical context is
preserved (the alerts page still shows them in the dismissed view).

Idempotent: re-running is a no-op since the WHERE filter only catches
open / acknowledged rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb353c9d4e1f"
down_revision: Union[str, None] = "dwb346b8e2c91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # alerts.status is an enum with values (open, acknowledged, resolved).
    # The codebase's dismiss-all flow sets open -> acknowledged + resolved_at;
    # we follow the same convention here so the dashboard's "dismissed"
    # view (= acknowledged with resolved_at set) lights up for these rows.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE alerts "
            "SET status = 'acknowledged', resolved_at = NOW() "
            "WHERE status = 'open' "
            "AND ("
            "  title LIKE 'Tokens not reported for %' "
            "  OR title LIKE 'Unattributed hook session: %'"
            ")"
        )
    )


def downgrade() -> None:
    # No-op: dismissing alerts is a one-way data scrub. We can't tell from
    # the dismissed row which were originally open vs acknowledged, and
    # rehydrating dead alert classes would defeat the point of the
    # cleanup. If a downgrade is needed for the schema, alerts that
    # accumulate after the downgrade will still fire via the resurrected
    # code paths.
    pass
