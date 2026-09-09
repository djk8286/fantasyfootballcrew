"""add draft scheduling

Revision ID: a5aac5703233
Revises: a067adf86e5c
Create Date: 2026-09-08 17:20:55.871851

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5aac5703233'
down_revision: Union[str, Sequence[str], None] = 'a067adf86e5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Only the two new columns -- see a067adf86e5c's identical note on
    # why the rest of autogenerate's diff (pre-existing SQLite-vs-model
    # drift, unrelated to this change) isn't included here.
    op.add_column('drafts', sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True))
    op.add_column('drafts', sa.Column('reminder_email_sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('drafts', 'reminder_email_sent_at')
    op.drop_column('drafts', 'scheduled_for')
