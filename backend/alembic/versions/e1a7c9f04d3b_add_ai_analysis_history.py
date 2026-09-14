"""add ai analysis history

Revision ID: e1a7c9f04d3b
Revises: 16993ffa9c32
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a7c9f04d3b'
down_revision: Union[str, Sequence[str], None] = '16993ffa9c32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Persisted history for the personal AI Analysis tools (Lineup/
    # Trade/Bet) -- see AIAnalysisHistory's model docstring. A new
    # table -- FK inline in create_table, same "no ALTER gotcha on a
    # fresh table" precedent as chat_messages/ai_usage_events.
    # Append-only log, no unique constraint, just the composite index
    # for the only access pattern this table has: "this user's history
    # for this tool, most recent first."
    op.create_table(
        'ai_analysis_history',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('league_id', sa.String(), sa.ForeignKey('leagues.id'), nullable=True),
        sa.Column('analysis_type', sa.String(), nullable=False),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('result', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        'ix_ai_analysis_history_user_type_created',
        'ai_analysis_history', ['user_id', 'analysis_type', 'created_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ai_analysis_history_user_type_created', table_name='ai_analysis_history')
    op.drop_table('ai_analysis_history')
