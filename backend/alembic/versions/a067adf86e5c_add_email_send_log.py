"""add email send log

Revision ID: a067adf86e5c
Revises: 47a59529566c
Create Date: 2026-09-08 14:13:00.319462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a067adf86e5c'
down_revision: Union[str, Sequence[str], None] = '47a59529566c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Only the new table -- autogenerate also picked up a pile of
    # pre-existing SQLite-vs-model drift (NOT NULL/FK/enum differences
    # that SQLite doesn't enforce the same way Postgres does, so the dev
    # DB and the models have quietly disagreed on these for a while).
    # Deliberately NOT included here -- unverified, unrelated to this
    # change, and risky to apply blind against production.
    op.create_table('email_send_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('to_email', sa.String(), nullable=False),
    sa.Column('email_type', sa.String(), nullable=False),
    sa.Column('subject', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('error_detail', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_send_logs_created', 'email_send_logs', ['created_at'], unique=False)
    op.create_index('ix_email_send_logs_status_created', 'email_send_logs', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_email_send_logs_to_email'), 'email_send_logs', ['to_email'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_email_send_logs_to_email'), table_name='email_send_logs')
    op.drop_index('ix_email_send_logs_status_created', table_name='email_send_logs')
    op.drop_index('ix_email_send_logs_created', table_name='email_send_logs')
    op.drop_table('email_send_logs')
