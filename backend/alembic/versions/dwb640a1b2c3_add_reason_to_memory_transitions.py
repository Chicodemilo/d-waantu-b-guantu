"""Persist the reason an adopting agent gives for its tiering decision.

Revision ID: dwb640a1b2c3
Revises: dwb631a1b2c3
Create Date: 2026-10-06

WHAT WAS BROKEN

`DecideRequest` has carried a `reason` field from the start, and
`decide_and_maybe_cut_over` passed it onward. Only the SKIP branch used it:
`skip()` appends it to the journal entry it writes. The TIERING branch dropped
it on the floor, because `decide()` did not declare the parameter at all.

The API accepted the field and returned 200 either way, so nothing reported a
problem and nothing could. This is the silent-success shape: a request that is
honoured in part, answered as though honoured in full.

WHAT IT COST, measured rather than estimated

IND's adoption to human_memory ran on 2026-10-06: 308 entries, seven agents.

    state      rows
    written    293   <- reason discarded
    skipped     15   <- reason survived, in the journal

293 reasons gone. They are not recoverable from anywhere: no log carries the
request body, and the agents that wrote them are ephemeral.

The damage is not that the prose is pretty. An adopting agent is handed ONE
entry at a time and is forbidden the queue by design, so the `reason` field is
its only channel for saying "a human needs to look at this one". The team lead
of that project flagged fifteen standing rulings that way, reported them as
recoverable, and was wrong: there was no column. The count was also wrong (it
was twenty), which is exactly the error a persisted flag would have made
impossible to make.

WHY A COLUMN RATHER THAN FOLDING IT INTO THE JOURNAL

The skip path's journal note is the right home for a skip, because a skipped
entry has no store row to hang anything on. A tiered entry does. Putting the
reason beside `decided_tier` and `decided_by` keeps the three facts of one
decision in one row - what was chosen, by whom, and why - which is what a later
reader is actually asking for.

NULLABLE, and the two reasons are different

The field is optional on the request, so a caller that omits it is not an
error. And every row written before this migration has a genuinely unknown
reason rather than an empty one; backfilling a placeholder would assert
something false about 293 rows whose reasoning was destroyed.

NOT RETROACTIVE. This fixes the next adoption. IND's is already done.
"""

from alembic import op
import sqlalchemy as sa

revision = "dwb640a1b2c3"
down_revision = "dwb631a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_transitions",
        sa.Column("reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Dropping this discards reasoning that exists nowhere else - the request
    # body is not logged and the deciding agent is gone. A downgrade is data
    # loss here, not a schema reversal, which is worth knowing before running
    # it rather than after.
    op.drop_column("memory_transitions", "reason")
