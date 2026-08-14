"""add commissioner digests

Revision ID: 8c382207a84b
Revises: 40c39ae88a57
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c382207a84b'
down_revision: Union[str, Sequence[str], None] = '40c39ae88a57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # AI-Assisted Commissioner Tools (Phase 8). A new table, so the FK
    # constraints are inline in create_table (no ALTER-add-FK gotcha --
    # that only bit Phase 7's add_column on an EXISTING table). The
    # unique constraint is also inline (as a table_args-style positional
    # UniqueConstraint), not a separate create_unique_constraint call --
    # SQLite can't ALTER-add a constraint post-creation either, only
    # bake it into the initial CREATE TABLE statement.
    op.create_table(
        'commissioner_digests',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('league_id', sa.String(), sa.ForeignKey('leagues.id'), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('generated_by', sa.String(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('league_id', 'week', 'year', name='uq_commissioner_digest_league_week_year'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('commissioner_digests')
