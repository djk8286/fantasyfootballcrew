"""add ai usage events

Revision ID: a40c6e3cb1a9
Revises: 838577fbc0ff
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a40c6e3cb1a9'
down_revision: Union[str, Sequence[str], None] = '838577fbc0ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Per-league daily AI usage cap. A new table -- FK inline in
    # create_table, same "no ALTER gotcha on a fresh table" precedent
    # as chat_messages/commissioner_digests. Append-only log, no
    # unique constraint.
    op.create_table(
        'ai_usage_events',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('league_id', sa.String(), sa.ForeignKey('leagues.id'), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ai_usage_events_league_created', 'ai_usage_events', ['league_id', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ai_usage_events_league_created', table_name='ai_usage_events')
    op.drop_table('ai_usage_events')
