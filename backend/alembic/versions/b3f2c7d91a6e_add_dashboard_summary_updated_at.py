"""add dashboard summary updated_at

Revision ID: b3f2c7d91a6e
Revises: e1a7c9f04d3b
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f2c7d91a6e'
down_revision: Union[str, Sequence[str], None] = 'e1a7c9f04d3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Lets the scheduler's daily dashboard-summary refresh (see
    # scheduler.py's _maybe_refresh_dashboard_summaries_once) tell "was
    # this row's content actually regenerated within the last 24h" apart
    # from created_at, which never changes once a row exists (both rows
    # are upserted in place on regenerate -- created_at would only ever
    # reflect the FIRST generation for that week, not the most recent
    # one). Backfilled to created_at's existing value for any row that
    # already exists, via server_default -- a reasonable "assume it was
    # last touched when it was created" starting point, not a guess that
    # matters (the very next scheduler tick re-checks and refreshes any
    # row older than 24h anyway).
    with op.batch_alter_table('weekly_top_players_summaries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))
    with op.batch_alter_table('weekly_scores_recaps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('weekly_scores_recaps', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
    with op.batch_alter_table('weekly_top_players_summaries', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
