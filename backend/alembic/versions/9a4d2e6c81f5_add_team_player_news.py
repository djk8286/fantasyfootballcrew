"""add team player news

Revision ID: 9a4d2e6c81f5
Revises: b3f2c7d91a6e
Create Date: 2026-09-22 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a4d2e6c81f5'
down_revision: Union[str, Sequence[str], None] = 'b3f2c7d91a6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Per-team AI news digest -- see TeamPlayerNews' model docstring.
    # A new table -- FK inline in create_table, same "no ALTER gotcha
    # on a fresh table" precedent as chat_messages/ai_usage_events.
    # One row per team_id (unique, upserted on regenerate), not an
    # append-only log like those two.
    op.create_table(
        'team_player_news',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('team_id', sa.String(), sa.ForeignKey('teams.id'), nullable=False, unique=True),
        sa.Column('league_id', sa.String(), sa.ForeignKey('leagues.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('player_snapshot', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('team_player_news')
