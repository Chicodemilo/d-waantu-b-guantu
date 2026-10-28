"""Move the adoption heading paths out of `context_key` into `adopted_from_heading`.

Revision ID: dwb710a1b2c3
Revises: dwb704a1b2c3
Create Date: 2026-10-28

WHAT THIS MOVES AND WHY

`memory_decide.decide` set `context_key` to `" / ".join(heading_path)` while
adopting a markdown `memory.md`, so 380 scars carry the heading path of the
section they came from in the column the SCAN reads as a SCOPE. The value is
FALSE AS A SCOPE - `scan_context` returns `unresolvable` for every one of them,
measured over all of them with the production resolvers against 29 epics, zero
resolving - and TRUE AS PROVENANCE. `decide` will never run again, so the
heading path is the only surviving pointer to where each lesson came from.

Nulling was proposed on DWB-705 and refused: `unresolvable` and NULL both take
no action, so the change had zero behavioural benefit against a permanent and
total information cost. This migration is the approved third option - put the
value where it is true, and null the column where it lies.

WHICH ROWS, AND WHY NOT ALL 425

Only rows with a `memory_transitions` row pointing at them. `decide` always
sets `target_memory_id`, so the link is a verifiable witness of adoption rather
than a judgement about what a string looks like.

    keyed scars                                        425
      adopted - a transition row points at them        380   <- moved here
      author-supplied via raw_memory.append_raw_memory  45   <- untouched
    WORKING rows with an author-supplied key            23   <- untouched

The 45 and the 23 were written by authors typing a heading-shaped string into
the scope field on 1, 7, 8 and 28 October. They never came from a `memory.md`,
so writing them into a column named `adopted_from_heading` would state
something false about their origin - the same category error this migration
exists to end, pointing the other way. They are LEFT AS THEY ARE, decided and
not overlooked: nulling them buys nothing behaviourally, and unlike the 380
they are a human's own words rather than pipeline output, which makes deleting
them a larger act than deleting a generated artifact.

THE SELECTION IS A JOIN, NOT AN ID LIST

Written as a join so it is reproducible and correct on any install rather than
true only of this database at the moment it was authored. DWB is the only
install that has ever adopted, so this is a no-op everywhere else - which is
the behaviour a hardcoded id list would silently fail to have.

`tier = 'scar'` is belt and braces: `decide` only ever set `context_key` for
scars, so the join already yields exactly the 380. It is here so that a future
adopted row of another tier is excluded by the statement rather than by a fact
about history.

THE DOWNGRADE IS A REAL REVERSE, AND IT IS THE SAFETY NET

The data is MOVED, never dropped, so `downgrade` restores every value to
`context_key` before removing the column. That matters more than the snapshot
taken alongside this ticket: a file in a scratchpad is one accident from gone,
whereas a reversible migration is recoverable by running it. The guard on the
restore (`context_key IS NULL`) means a downgrade cannot overwrite a scope some
later work legitimately set on one of these rows.

NO INDEX. Nothing queries by this column; it is read back beside the row it
belongs to, and `context_key` carries no index either.
"""

import sqlalchemy as sa
from alembic import op

revision = "dwb710a1b2c3"
down_revision = "dwb704a1b2c3"
branch_labels = None
depends_on = None

# Nullable, unlike DWB-704's `context_free`, and the difference is the same one
# that column's own docstring draws. `context_free` is a DECLARATION every row
# either has or has not made, so False says something true about all of them.
# This is a FACT that exists only for rows that came through adoption; NULL
# means "this lesson did not come from an adopted memory.md", which is correct
# for every other row and is not a gap.
_MOVE = sa.text(
    """
    UPDATE agent_memories AS am
    JOIN memory_transitions AS mt ON mt.target_memory_id = am.id
       SET am.adopted_from_heading = am.context_key,
           am.context_key = NULL
     WHERE am.context_key IS NOT NULL
       AND am.tier = 'scar'
    """
)

_RESTORE = sa.text(
    """
    UPDATE agent_memories
       SET context_key = adopted_from_heading,
           adopted_from_heading = NULL
     WHERE adopted_from_heading IS NOT NULL
       AND context_key IS NULL
    """
)


def upgrade() -> None:
    op.add_column(
        "agent_memories",
        sa.Column("adopted_from_heading", sa.String(length=255), nullable=True),
    )
    op.execute(_MOVE)


def downgrade() -> None:
    op.execute(_RESTORE)
    op.drop_column("agent_memories", "adopted_from_heading")
