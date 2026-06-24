# Path: app/services/inter_agent_message.py
# File: inter_agent_message.py
# Created: 2026-06-24
# Purpose: Service-layer logic for captured inter-agent messages - the age-based
#          retention purge (DWB-449). The capture write itself lives in
#          hook_tracking.handle_agent_message; the list/delete are inline in the
#          projects router. This module owns the periodic server-side sweep.
# Caller: app/services/idle_sweeper.py (purge loop)
# Callees: app.models.inter_agent_message.InterAgentMessage
# Data In: max_age_days threshold, optional now() override (tests)
# Data Out: count of purged rows
# Last Modified: 2026-06-24

"""Age-based retention purge for inter_agent_messages (DWB-449).

The purge is PERIODIC - it rides the existing idle-session sweeper loop rather
than firing on session close. It keys off ``created_at`` ALONE (never
``dwb_session_id``, which is display-only), so a message outlives the session
it was sent in and is removed strictly on age.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.inter_agent_message import InterAgentMessage


def purge_old_agent_messages(
    db: Session,
    *,
    max_age_days: int,
    now: datetime | None = None,
) -> int:
    """Delete inter_agent_messages whose ``created_at`` is older than
    ``max_age_days`` before ``now``. Returns the number of rows removed.

    ``now`` defaults to the DB clock (``func.now()``) so the comparison happens
    server-side in one statement; tests pass an explicit ``now`` for a
    deterministic cutoff. ``max_age_days <= 0`` is a no-op (purge disabled).
    The caller owns the commit.
    """
    if max_age_days <= 0:
        return 0

    if now is None:
        cutoff = func.now() - timedelta(days=max_age_days)
    else:
        cutoff = now - timedelta(days=max_age_days)

    # Count first so we can report exactly how many were purged (no silent caps).
    to_purge = db.scalar(
        select(func.count())
        .select_from(InterAgentMessage)
        .where(InterAgentMessage.created_at < cutoff)
    ) or 0
    if not to_purge:
        return 0

    db.execute(
        delete(InterAgentMessage).where(InterAgentMessage.created_at < cutoff)
    )
    return int(to_purge)
