"""add fantasy golf tables and leagues.sport

Revision ID: a9f3c2e71b40
Revises: b3d5f7a9c1e2
Create Date: 2026-10-18 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9f3c2e71b40'
down_revision: Union[str, Sequence[str], None] = 'b3d5f7a9c1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(name):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # Additive only. Existing leagues backfill to 'nfl' via server default.
    # Booleans use sa.false() (0 on SQLite, false on Postgres) -- never 'false'.
    op.add_column('leagues', sa.Column('sport', sa.String(length=16), server_default='nfl', nullable=False))

    op.create_table('golf_tournaments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('espn_event_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('tour', sa.String(length=16), server_default='pga', nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='scheduled', nullable=False),
        sa.Column('is_major', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('course', sa.String(), nullable=True),
        sa.Column('purse', sa.Float(), nullable=True),
        sa.Column('tiers_assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_json', sa.JSON(), nullable=True),
        _ts('created_at'), _ts('updated_at'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('espn_event_id'),
    )
    op.create_index('ix_golf_tournaments_season_start', 'golf_tournaments', ['season', 'start_date'])

    op.create_table('golfers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('espn_athlete_id', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('short_name', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=True),
        sa.Column('is_amateur', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('headshot_url', sa.String(), nullable=True),
        sa.Column('season_points', sa.Float(), server_default='0', nullable=False),
        sa.Column('season_earnings', sa.Float(), server_default='0', nullable=False),
        _ts('created_at'), _ts('updated_at'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('espn_athlete_id'),
    )

    op.create_table('golf_field_entries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('tournament_id', sa.String(), nullable=False),
        sa.Column('golfer_id', sa.String(), nullable=False),
        sa.Column('tier', sa.Integer(), nullable=True),
        sa.Column('tee_time_r1', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='active', nullable=False),
        sa.Column('position', sa.String(length=8), nullable=True),
        sa.Column('to_par', sa.Integer(), nullable=True),
        sa.Column('total_strokes', sa.Integer(), nullable=True),
        sa.Column('thru', sa.Integer(), nullable=True),
        sa.Column('earnings', sa.Float(), nullable=True),
        sa.Column('cup_points', sa.Float(), nullable=True),
        sa.Column('rounds', sa.JSON(), nullable=True),
        _ts('updated_at'),
        sa.ForeignKeyConstraint(['tournament_id'], ['golf_tournaments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['golfer_id'], ['golfers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tournament_id', 'golfer_id', name='uq_golf_field_entry'),
    )
    op.create_index('ix_golf_field_entries_tournament_tier', 'golf_field_entries', ['tournament_id', 'tier'])

    op.create_table('golf_picks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('league_id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=False),
        sa.Column('tournament_id', sa.String(), nullable=False),
        sa.Column('tier', sa.Integer(), nullable=False),
        sa.Column('golfer_id', sa.String(), nullable=False),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        _ts('created_at'), _ts('updated_at'),
        sa.ForeignKeyConstraint(['league_id'], ['leagues.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tournament_id'], ['golf_tournaments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['golfer_id'], ['golfers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', 'tournament_id', 'tier', name='uq_golf_pick_team_event_tier'),
    )
    op.create_index('ix_golf_picks_league_tournament', 'golf_picks', ['league_id', 'tournament_id'])

    op.create_table('golf_team_event_results',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('league_id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=False),
        sa.Column('tournament_id', sa.String(), nullable=False),
        sa.Column('counted_to_par', sa.Integer(), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('season_points', sa.Float(), server_default='0', nullable=False),
        sa.Column('is_final', sa.Boolean(), server_default=sa.false(), nullable=False),
        _ts('updated_at'),
        sa.ForeignKeyConstraint(['league_id'], ['leagues.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tournament_id'], ['golf_tournaments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', 'tournament_id', name='uq_golf_result_team_event'),
    )
    op.create_index('ix_golf_results_league_tournament', 'golf_team_event_results', ['league_id', 'tournament_id'])


def downgrade() -> None:
    op.drop_index('ix_golf_results_league_tournament', table_name='golf_team_event_results')
    op.drop_table('golf_team_event_results')
    op.drop_index('ix_golf_picks_league_tournament', table_name='golf_picks')
    op.drop_table('golf_picks')
    op.drop_index('ix_golf_field_entries_tournament_tier', table_name='golf_field_entries')
    op.drop_table('golf_field_entries')
    op.drop_table('golfers')
    op.drop_index('ix_golf_tournaments_season_start', table_name='golf_tournaments')
    op.drop_table('golf_tournaments')
    with op.batch_alter_table('leagues') as batch_op:
        batch_op.drop_column('sport')
