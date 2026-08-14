"""add user token_version

Revision ID: 7f26b8c40cd9
Revises: a40c6e3cb1a9
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f26b8c40cd9'
down_revision: Union[str, Sequence[str], None] = 'a40c6e3cb1a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Auth Security Hardening, Step 2. Plain column, server default 0
    # so every existing user backfills to "no password change yet" --
    # their currently-issued tokens (which carry no token_version claim
    # at all) are treated as version 0 by get_current_user's check.
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'token_version')
