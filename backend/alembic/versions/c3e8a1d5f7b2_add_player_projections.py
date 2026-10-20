"""add player_projections

Revision ID: c3e8a1d5f7b2
Revises: b7d1e4f9a2c6
Create Date: 2026-10-19 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3e8a1d5f7b2'
down_revision: Union[str, Sequence[str], None] = 'b7d1e4f9a2c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New empty table. The scheduler fills it; nothing is backfilled.
    op.create_table(
        'player_projections',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('player_id', sa.String(), sa.ForeignKey('players.id', ondelete='CASCADE'), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('stats', sa.JSON(), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id', 'year', 'week', name='uq_player_projection_week'),
    )
    op.create_index('ix_player_projections_player_id', 'player_projections', ['player_id'])
    op.create_index('ix_player_projections_year_week', 'player_projections', ['year', 'week'])


def downgrade() -> None:
    op.drop_index('ix_player_projections_year_week', table_name='player_projections')
    op.drop_index('ix_player_projections_player_id', table_name='player_projections')
    op.drop_table('player_projections')
