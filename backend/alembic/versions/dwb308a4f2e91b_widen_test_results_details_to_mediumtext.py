# Path: alembic/versions/dwb308a4f2e91b_widen_test_results_details_to_mediumtext.py
# File: dwb308a4f2e91b_widen_test_results_details_to_mediumtext.py
# Created: 2026-06-05
# Purpose: Widen test_results.details from TEXT (64KB) to MEDIUMTEXT (16MB) so the
#          gate-sized payload (per-test list + 4000-char output tail) survives a POST.
# Caller: alembic upgrade head
# Callees: alembic.op (ALTER COLUMN)
# Data In: existing test_results.details column (TEXT)
# Data Out: test_results.details column (MEDIUMTEXT)
# Last Modified: 2026-06-05

"""widen test_results.details to MEDIUMTEXT (DWB-308)

Revision ID: dwb308a4f2e91b
Revises: dwb305c7f1e2a
Create Date: 2026-06-05 13:55:00.000000

The DWB gate-run payload (577+ per-test entries + standard 4000-char output
tail) builds a `details` JSON blob in the 85-100KB range. The previous
column type (TEXT) caps at 65,535 bytes, so MySQL raised a Data too long
error and the POST returned HTTP 500.

MEDIUMTEXT caps at 16,777,215 bytes (~16MB), which is comfortably above any
realistic suite — a 5000-test suite with full per-test data is still well
under 1MB.

Down-migration narrows back to TEXT. If any row currently exceeds 65,535
bytes the narrowing will fail; callers must clean up first.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT


# revision identifiers, used by Alembic.
revision: str = "dwb308a4f2e91b"
down_revision: Union[str, None] = "dwb305c7f1e2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "test_results",
        "details",
        existing_type=sa.Text(),
        type_=MEDIUMTEXT(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "test_results",
        "details",
        existing_type=MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=True,
    )
