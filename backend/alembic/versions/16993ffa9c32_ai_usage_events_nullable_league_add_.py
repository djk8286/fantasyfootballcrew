"""ai usage events nullable league, add user id

Revision ID: 16993ffa9c32
Revises: 2fb6ca1c8a98
Create Date: 2026-09-09 23:15:08.720317

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16993ffa9c32'
down_revision: Union[str, Sequence[str], None] = '2fb6ca1c8a98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Only the real change -- see AIUsageEvent's model docstring. Same
    # convention as every recent migration in this repo: autogenerate's
    # full diff also picked up a pile of unrelated pre-existing
    # SQLite-vs-model drift (NOT NULL tightening on several other
    # tables' created_at, the notifications.type Enum/VARCHAR mismatch,
    # teams.partner_team_id's FK, the orphaned drafts.scheduled_for/
    # reminder_email_sent_at columns) that isn't part of this change.
    #
    # SQLite has no native ALTER COLUMN -- batch mode recreates the
    # table under the hood, which is what lets nullable/type changes
    # work there at all (Postgres, prod's real target, supports
    # alter_column directly; batch mode is a correct no-op wrapper
    # for it too).
    with op.batch_alter_table('ai_usage_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.String(), nullable=True))
        batch_op.alter_column('league_id', existing_type=sa.VARCHAR(), nullable=True)
        batch_op.create_index('ix_ai_usage_events_user_created', ['user_id', 'created_at'], unique=False)
        batch_op.create_foreign_key('fk_ai_usage_events_user_id', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('ai_usage_events', schema=None) as batch_op:
        batch_op.drop_constraint('fk_ai_usage_events_user_id', type_='foreignkey')
        batch_op.drop_index('ix_ai_usage_events_user_created')
        batch_op.alter_column('league_id', existing_type=sa.VARCHAR(), nullable=False)
        batch_op.drop_column('user_id')
