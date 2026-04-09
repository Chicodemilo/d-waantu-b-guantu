"""make jira_issue_key unique (1:1)

Revision ID: 055dd4b1a2dd
Revises: eb85526c2ade
Create Date: 2026-04-09 15:35:16.224295

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '055dd4b1a2dd'
down_revision: Union[str, None] = 'eb85526c2ade'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f('ix_tickets_jira_issue_key'), table_name='tickets')
    op.create_index(op.f('ix_tickets_jira_issue_key'), 'tickets', ['jira_issue_key'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_tickets_jira_issue_key'), table_name='tickets')
    op.create_index(op.f('ix_tickets_jira_issue_key'), 'tickets', ['jira_issue_key'], unique=False)
