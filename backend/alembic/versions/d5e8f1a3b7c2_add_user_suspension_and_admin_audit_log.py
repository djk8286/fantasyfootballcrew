"""add user suspension and admin audit log

Revision ID: d5e8f1a3b7c2
Revises: c41a7e2b9d10
Create Date: 2026-10-17 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e8f1a3b7c2'
down_revision: Union[str, Sequence[str], None] = 'c41a7e2b9d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Additive only. is_suspended gets a server default so existing rows
    # backfill to false without a separate UPDATE. sa.false() rather than
    # the string 'false' (which 47a59529566c used for is_admin): on SQLite
    # the string is stored literally as TEXT 'false', which reads back
    # TRUTHY -- every existing user would come back suspended. sa.false()
    # renders as `false` on Postgres and `0` on SQLite.
    op.add_column('users', sa.Column('is_suspended', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('suspended_reason', sa.String(), nullable=True))

    op.create_table('admin_audit_logs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('admin_user_id', sa.String(), nullable=False),
    sa.Column('admin_username', sa.String(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('target_type', sa.String(), nullable=False),
    sa.Column('target_id', sa.String(), nullable=False),
    sa.Column('target_label', sa.String(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_audit_logs_created', 'admin_audit_logs', ['created_at'], unique=False)
    op.create_index('ix_admin_audit_logs_target', 'admin_audit_logs', ['target_type', 'target_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_admin_audit_logs_target', table_name='admin_audit_logs')
    op.drop_index('ix_admin_audit_logs_created', table_name='admin_audit_logs')
    op.drop_table('admin_audit_logs')
    # batch mode so SQLite (no native DROP COLUMN on older versions) can
    # rebuild the table; on Postgres this is a plain ALTER TABLE.
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('suspended_reason')
        batch_op.drop_column('suspended_at')
        batch_op.drop_column('is_suspended')
