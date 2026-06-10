# Path: alembic/versions/dwb351d4f7a93_scrub_ai_phrase_persistence.py
# File: dwb351d4f7a93_scrub_ai_phrase_persistence.py
# Created: 2026-06-10
# Purpose: Backfill scrub - null out dwb_sessions.open_phrase / close_phrase for any AI-layer methods (DWB-351 privacy)
# Caller: alembic upgrade head
# Callees: alembic.op
# Data In: existing dwb_sessions rows
# Data Out: open_phrase=NULL where open_method IN (ai_confident, ai_asked); same for close
# Last Modified: 2026-06-10

"""scrub AI-layer phrase persistence (DWB-351)

Revision ID: dwb351d4f7a93
Revises: dwb353c9d4e1f
Create Date: 2026-06-10 13:55:00.000000

DWB-351 forbids persisting user-typed text. The service-layer guards in
``app.services.dwb_session.open_session`` and ``close_session`` now null
out the phrase fields for AI-layer methods, but historical rows from
before the guard landed may still carry user-typed strings.

This migration is a one-shot scrub:

  UPDATE dwb_sessions
     SET open_phrase = NULL
   WHERE open_method IN ('ai_confident', 'ai_asked')
     AND open_phrase IS NOT NULL;

  UPDATE dwb_sessions
     SET close_phrase = NULL
   WHERE close_method IN ('ai_confident', 'ai_asked')
     AND close_phrase IS NOT NULL;

Regex-method rows are untouched: the matched substring there is bounded
by the hardcoded catalogue in ``app.config.session_phrases`` and the
spec explicitly allows it. idle_timeout closes have no phrase to start
with so the WHERE clause is a no-op for them.

Idempotent: re-running matches zero rows since the service guard
prevents new AI-layer phrases from being written.

Downgrade is a no-op: we cannot recover the original user-typed text
(by design - it was never supposed to be persisted in the first place).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "dwb351d4f7a93"
down_revision: Union[str, None] = "dwb353c9d4e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE dwb_sessions "
            "SET open_phrase = NULL "
            "WHERE open_method IN ('ai_confident', 'ai_asked') "
            "AND open_phrase IS NOT NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE dwb_sessions "
            "SET close_phrase = NULL "
            "WHERE close_method IN ('ai_confident', 'ai_asked') "
            "AND close_phrase IS NOT NULL"
        )
    )


def downgrade() -> None:
    # No-op: the original phrase values are gone by design. Restoring
    # would require source data we deliberately discarded.
    pass
