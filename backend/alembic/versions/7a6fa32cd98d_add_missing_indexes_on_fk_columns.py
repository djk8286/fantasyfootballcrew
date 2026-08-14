"""add missing indexes on FK columns

Revision ID: 7a6fa32cd98d
Revises: 8b4e20e4d51a
Create Date: 2026-08-14 16:23:31.882495

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a6fa32cd98d'
down_revision: Union[str, Sequence[str], None] = '8b4e20e4d51a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    None of these FK columns had an index (confirmed by reading every
    prior migration directly, not just the model Mapped annotations --
    Postgres does not auto-index FKs). teams.league_id is the single
    biggest gap: nearly every standings/health/insights/draft service
    function opens with a `WHERE league_id = ...` filter on one of these
    tables, so each was a sequential scan in production today. Plain
    single-column indexes, not composites -- Postgres can combine
    multiple single-column indexes via a bitmap scan when a query
    filters more than one of these together, and the actual query shapes
    against these tables vary enough (draft_picks alone is filtered by
    draft_id, by (draft_id, team_id), and by (draft_id, player_id) from
    different call sites) that one single-column index per column is
    more broadly useful than guessing at one specific composite.
    """
    op.create_index("ix_teams_league_id", "teams", ["league_id"])
    op.create_index("ix_coaches_team_id", "coaches", ["team_id"])
    op.create_index("ix_draft_picks_draft_id", "draft_picks", ["draft_id"])
    op.create_index("ix_draft_picks_team_id", "draft_picks", ["team_id"])
    op.create_index("ix_draft_picks_player_id", "draft_picks", ["player_id"])
    op.create_index("ix_draft_picks_league_id", "draft_picks", ["league_id"])
    op.create_index("ix_score_adjustments_league_id", "score_adjustments", ["league_id"])
    op.create_index("ix_score_adjustments_team_id", "score_adjustments", ["team_id"])
    op.create_index("ix_transactions_league_id", "transactions", ["league_id"])
    op.create_index("ix_transactions_team_id", "transactions", ["team_id"])
    op.create_index("ix_scoring_configs_league_id", "scoring_configs", ["league_id"])
    op.create_index("ix_playoff_matchups_playoff_id", "playoff_matchups", ["playoff_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_playoff_matchups_playoff_id", table_name="playoff_matchups")
    op.drop_index("ix_scoring_configs_league_id", table_name="scoring_configs")
    op.drop_index("ix_transactions_team_id", table_name="transactions")
    op.drop_index("ix_transactions_league_id", table_name="transactions")
    op.drop_index("ix_score_adjustments_team_id", table_name="score_adjustments")
    op.drop_index("ix_score_adjustments_league_id", table_name="score_adjustments")
    op.drop_index("ix_draft_picks_league_id", table_name="draft_picks")
    op.drop_index("ix_draft_picks_player_id", table_name="draft_picks")
    op.drop_index("ix_draft_picks_team_id", table_name="draft_picks")
    op.drop_index("ix_draft_picks_draft_id", table_name="draft_picks")
    op.drop_index("ix_coaches_team_id", table_name="coaches")
    op.drop_index("ix_teams_league_id", table_name="teams")
