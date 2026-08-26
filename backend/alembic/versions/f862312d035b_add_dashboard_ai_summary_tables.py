"""add dashboard AI summary tables

Revision ID: f862312d035b
Revises: 7a6fa32cd98d
Create Date: 2026-08-25 17:12:31.593148

Four new tables for the Dashboard AI Summaries initiative:
- nfl_games: real NFL game scores/schedule, synced from ESPN's public
  scoreboard (this app's only source of real game-level data -- Sleeper
  gives per-player stats only, never a game object).
- weekly_top_players_summaries / weekly_scores_recaps: NFL-wide
  (unique on week+year, no league_id) AI summaries for the dashboard.
- team_weekly_recaps: per-league (unique on league_id+week+year) AI
  recap covering every team's week in one blurb-per-team LLM call.

Autogenerate also picked up unrelated pre-existing drift between the
local SQLite dev DB and the models (created_at NOT NULL on several
older tables, a notifications.type enum re-detection, teams.partner_team_id's
FK) -- none of that is a real change, it's SQLite's own reflection not
matching Postgres's actual behavior for these already-shipped columns,
so none of it is included here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f862312d035b'
down_revision: Union[str, Sequence[str], None] = '7a6fa32cd98d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'nfl_games',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('espn_event_id', sa.String(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('season_type', sa.Integer(), nullable=False),
        sa.Column('home_team', sa.String(), nullable=False),
        sa.Column('home_team_name', sa.String(), nullable=False),
        sa.Column('home_score', sa.Integer(), nullable=True),
        sa.Column('away_team', sa.String(), nullable=False),
        sa.Column('away_team_name', sa.String(), nullable=False),
        sa.Column('away_score', sa.Integer(), nullable=True),
        sa.Column('status_state', sa.String(), nullable=False),
        sa.Column('status_detail', sa.String(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False),
        sa.Column('kickoff_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('espn_event_id', name='uq_nfl_games_espn_event_id'),
    )
    op.create_index(op.f('ix_nfl_games_espn_event_id'), 'nfl_games', ['espn_event_id'], unique=False)
    op.create_index(op.f('ix_nfl_games_week'), 'nfl_games', ['week'], unique=False)
    op.create_index(op.f('ix_nfl_games_year'), 'nfl_games', ['year'], unique=False)

    op.create_table(
        'weekly_scores_recaps',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week', 'year', name='uq_weekly_scores_recap_week_year'),
    )

    op.create_table(
        'weekly_top_players_summaries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('top_players', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week', 'year', name='uq_weekly_top_players_summary_week_year'),
    )

    op.create_table(
        'team_weekly_recaps',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('league_id', sa.String(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('generated_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['generated_by'], ['users.id']),
        sa.ForeignKeyConstraint(['league_id'], ['leagues.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('league_id', 'week', 'year', name='uq_team_weekly_recap_league_week_year'),
    )
    op.create_index(op.f('ix_team_weekly_recaps_league_id'), 'team_weekly_recaps', ['league_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_team_weekly_recaps_league_id'), table_name='team_weekly_recaps')
    op.drop_table('team_weekly_recaps')
    op.drop_table('weekly_top_players_summaries')
    op.drop_table('weekly_scores_recaps')
    op.drop_index(op.f('ix_nfl_games_year'), table_name='nfl_games')
    op.drop_index(op.f('ix_nfl_games_week'), table_name='nfl_games')
    op.drop_index(op.f('ix_nfl_games_espn_event_id'), table_name='nfl_games')
    op.drop_table('nfl_games')
