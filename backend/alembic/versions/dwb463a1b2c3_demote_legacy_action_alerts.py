# Path: alembic/versions/dwb463a1b2c3_demote_legacy_action_alerts.py
# File: dwb463a1b2c3_demote_legacy_action_alerts.py
# Created: 2026-06-24
# Purpose: One-time backfill dismissing legacy peer-scoring / sprint-close / test-run alert rows (DWB-463)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing alerts rows at dwb462a1b2c3
# Data Out: those three legacy alert types acknowledged so open_alerts drops
# Last Modified: 2026-06-24

"""demote legacy action-alerts to dismissed (DWB-463)

Revision ID: dwb463a1b2c3
Revises: dwb462a1b2c3
Create Date: 2026-06-24 15:00:00.000000

Hand-written data backfill (no schema change). Epic 37 "Alerts vs Actions"
demotes three event types from alerts to the activity feed going forward
(peer carrot/stick, sprint-close "tests needed" notice, ad-hoc test-run
request). This migration dismisses the EXISTING open rows of ONLY those three
types so the open_alerts count drops to reflect the new world.

It deliberately does NOT touch:
  - comms rows (TL-channel pings),
  - HUMAN scoring rows (title contains "from the human"),
  - other actionable rows (rework, missing gate file).

Dismissal = status 'acknowledged' + resolved_at now (mirrors the dismiss-all
convention). Only currently-open rows are affected. Downgrade is a no-op: the
original open/acknowledged split isn't recoverable and re-opening dismissed
rows would resurrect noise.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "dwb463a1b2c3"
down_revision: Union[str, None] = "dwb462a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Peer scoring: scoring-category rows that are NOT the human ("from the
    #    human") are peer carrots/sticks. Human scoring stays an alert.
    op.execute(
        "UPDATE alerts SET status = 'acknowledged', resolved_at = NOW() "
        "WHERE status = 'open' "
        "AND category = 'scoring' "
        "AND title NOT LIKE '%from the human%'"
    )
    # 2. Sprint-close "tests needed" notice.
    op.execute(
        "UPDATE alerts SET status = 'acknowledged', resolved_at = NOW() "
        "WHERE status = 'open' "
        "AND title LIKE 'Sprint %tests needed'"
    )
    # 3. Ad-hoc test-run request.
    op.execute(
        "UPDATE alerts SET status = 'acknowledged', resolved_at = NOW() "
        "WHERE status = 'open' "
        "AND title = 'Test run requested'"
    )


def downgrade() -> None:
    # No-op: the pre-backfill open/acknowledged split is not recoverable, and
    # re-opening these dismissed rows would resurrect the very noise DWB-463
    # removed.
    pass
