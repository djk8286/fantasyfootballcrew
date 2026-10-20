"""add draft_autopick (server-persisted per-team autopick toggle)

Revision ID: b5d1e8f2a7c3
Revises: a9f3c2e71b40
Create Date: 2026-10-19 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5d1e8f2a7c3'
down_revision: Union[str, Sequence[str], None] = 'a9f3c2e71b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive only: a new, empty table. No existing rows are touched.
    op.create_table('draft_autopick',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('draft_id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=False),
        # sa.false() -> 0 on SQLite, false on Postgres (never the TEXT 'false').
        sa.Column('enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('updated_by', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['draft_id'], ['drafts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('draft_id', 'team_id', name='uq_draft_autopick_draft_team'),
    )
    op.create_index('ix_draft_autopick_draft_id', 'draft_autopick', ['draft_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_draft_autopick_draft_id', table_name='draft_autopick')
    op.drop_table('draft_autopick')
