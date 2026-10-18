"""add player_news table and players.espn_id

Revision ID: a1c4e6f8b2d0
Revises: e7b2c9d4f6a1
Create Date: 2026-10-18 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c4e6f8b2d0'
down_revision: Union[str, Sequence[str], None] = 'e7b2c9d4f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Additive only."""
    op.add_column('players', sa.Column('espn_id', sa.String(), nullable=True))
    op.create_index('ix_players_espn_id', 'players', ['espn_id'], unique=False)
    op.create_table(
        'player_news',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('player_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('headline', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source', 'external_id', 'player_id', name='uq_player_news_article_player'),
    )
    op.create_index('ix_player_news_player_id', 'player_news', ['player_id'], unique=False)
    op.create_index('ix_player_news_published_at', 'player_news', ['published_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_player_news_published_at', table_name='player_news')
    op.drop_index('ix_player_news_player_id', table_name='player_news')
    op.drop_table('player_news')
    op.drop_index('ix_players_espn_id', table_name='players')
    with op.batch_alter_table('players') as batch_op:
        batch_op.drop_column('espn_id')
