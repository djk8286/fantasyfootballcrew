"""add draft queue entries

Revision ID: 2fb6ca1c8a98
Revises: a5aac5703233
Create Date: 2026-09-09 22:19:56.516508

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fb6ca1c8a98'
down_revision: Union[str, Sequence[str], None] = 'a5aac5703233'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Only the new table -- same convention as a067adf86e5c/a5aac5703233's
    # own notes: autogenerate's full diff also picked up a pile of
    # pre-existing SQLite-vs-model drift (NOT NULL tightening on several
    # unrelated tables' created_at, the notifications.type Enum/VARCHAR
    # mismatch, teams.partner_team_id's FK, and the now-orphaned
    # drafts.scheduled_for/reminder_email_sent_at columns from the
    # reverted draft-scheduling feature) that isn't part of this change
    # and shouldn't ride along on it.
    op.create_table('draft_queue_entries',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('draft_id', sa.String(), nullable=False),
    sa.Column('team_id', sa.String(), nullable=False),
    sa.Column('player_id', sa.String(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['draft_id'], ['drafts.id'], ),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('draft_id', 'team_id', 'player_id', name='uq_draft_queue_team_player')
    )
    op.create_index('ix_draft_queue_draft_team_position', 'draft_queue_entries', ['draft_id', 'team_id', 'position'], unique=False)
    op.create_index(op.f('ix_draft_queue_entries_draft_id'), 'draft_queue_entries', ['draft_id'], unique=False)
    op.create_index(op.f('ix_draft_queue_entries_team_id'), 'draft_queue_entries', ['team_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_draft_queue_entries_team_id'), table_name='draft_queue_entries')
    op.drop_index(op.f('ix_draft_queue_entries_draft_id'), table_name='draft_queue_entries')
    op.drop_index('ix_draft_queue_draft_team_position', table_name='draft_queue_entries')
    op.drop_table('draft_queue_entries')
