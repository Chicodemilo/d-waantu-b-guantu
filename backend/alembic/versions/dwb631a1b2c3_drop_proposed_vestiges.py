"""DWB-631: drop the proposed/decided vestiges from the transition surface.

Revision ID: dwb631a1b2c3
Revises: dwb611a1b2c3
Create Date: 2026-10-01

WHAT IS BEING REMOVED AND WHY IT IS A REMOVAL RATHER THAN A FIX

`TransitionState.proposed`, `TransitionState.decided` and the `proposed_tier`
column describe a two-phase adoption flow that the spec RULES OUT. Section 4:
the snapshot makes no judgement, because an agent shown a proposed answer
agrees with it, and that rubber-stamp is the thing the design exists to
prevent (`routers/memory_transitions.py:23-24`, `services/memory_adopt.py:24`).

So these were not forgotten, they were abandoned. Nothing in `app/` has ever
written any of the three: verified by AST scan over every assignment to
`.state` and every `tier=` keyword, by grep filtering out the lookalike
identifiers `decided_tier`/`decided_by`/`decided_at`, and against the data.

VERIFIED AGAINST THE DATA BEFORE DROPPING, not against the code:

    memory_transitions.state values present:  written 396, skipped 6
    rows with a non-null proposed_tier:       0 of 402

So no persisted row holds either state or any proposed tier.

WHY A MIGRATION RATHER THAN A COMMENT. Before this, "the snapshot carries no
proposed tier" was a CONVENTION guarded by three tests asserting absence, and
an absence assertion holds only until someone writes the line nobody
anticipated. After it, the rubber-stamp flow is UNSPELLABLE: there is no field
to put a proposal in and no state to park it in, so reintroducing it means
deliberately adding a column and a migration, which is a reviewable act rather
than an omission.

A VESTIGE INSIDE THE VESTIGE, recorded so the next reader finds the
explanation rather than the puzzle: `proposed_tier`'s enum still declared
`scar_context_bound`, a MemoryTier value that DWB-611 collapsed into `scar`.
It was unreachable through a column nothing wrote. It disappears with the
column rather than needing its own cleanup.

ORDERING NOTE FOR WHOEVER REPLAYS THIS. The model edit must land BEFORE this
migration is applied, not after. SQLAlchemy names every mapped column in its
SELECT, so a dropped column with a live mapping raises 1054 on every read of
the table; the reverse - a mapping dropped while the column survives - is
inert. `create_all` under `--reload` never drops a column, so saving the model
cannot pre-empt this.
"""

import sqlalchemy as sa
from alembic import op

revision = "dwb631a1b2c3"
down_revision = "dwb611a1b2c3"
branch_labels = None
depends_on = None

# The state enum as it stands, and as it will stand. `journaled` is NOT touched
# here: it also has no writer, but a reporting field derives from it and the
# cutover guard holds a definition of it, so it carries live consequences these
# two do not. That is DWB-622's territory and it stays.
_STATE_BEFORE = ("pending", "proposed", "decided", "written", "skipped", "journaled")
_STATE_AFTER = ("pending", "written", "skipped", "journaled")

# The tier enum as the dropped column declared it, including the collapsed
# value, so the downgrade restores exactly what was there.
_TIERS_AS_DROPPED = ("raw", "core", "scar", "scar_context_bound", "working")


def upgrade() -> None:
    # Narrow the state enum first. Safe in either order here because no row
    # holds a removed value, but doing it before the column drop keeps the
    # two changes to this table adjacent.
    op.alter_column(
        "memory_transitions",
        "state",
        existing_type=sa.Enum(*_STATE_BEFORE, name="transitionstate"),
        type_=sa.Enum(*_STATE_AFTER, name="transitionstate"),
        existing_nullable=False,
    )
    op.drop_column("memory_transitions", "proposed_tier")


def downgrade() -> None:
    # Restores the column nullable and the enum wide. It cannot restore VALUES,
    # because there were none: every row held NULL and no state row held
    # `proposed` or `decided`. So this downgrade is lossless in fact rather
    # than merely in intent.
    op.add_column(
        "memory_transitions",
        sa.Column(
            "proposed_tier",
            sa.Enum(*_TIERS_AS_DROPPED, name="memorytier"),
            nullable=True,
        ),
    )
    op.alter_column(
        "memory_transitions",
        "state",
        existing_type=sa.Enum(*_STATE_AFTER, name="transitionstate"),
        type_=sa.Enum(*_STATE_BEFORE, name="transitionstate"),
        existing_nullable=False,
    )
