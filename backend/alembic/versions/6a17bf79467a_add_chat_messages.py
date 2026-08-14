"""add chat messages

Revision ID: 6a17bf79467a
Revises: 569afcfa7cd9
Create Date: 2026-08-14 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a17bf79467a'
down_revision: Union[str, Sequence[str], None] = '569afcfa7cd9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # AI Co-Commissioner Chat (AI Co-Commissioner v1, deferred item 7).
    # A new table -- FK inline in create_table, same "no ALTER gotcha
    # on a fresh table" precedent as 8c382207a84b. No unique
    # constraint this time (append-only conversation log, not a
    # one-row-per-period upsert), so just the composite index for the
    # only access pattern this table has: "this league's chat history,
    # in order."
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('league_id', sa.String(), sa.ForeignKey('leagues.id'), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_chat_messages_league_created', 'chat_messages', ['league_id', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_messages_league_created', table_name='chat_messages')
    op.drop_table('chat_messages')
