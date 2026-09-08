"""add is_admin to users

Revision ID: 47a59529566c
Revises: 63365882ae25
Create Date: 2026-09-08 13:35:48.656279

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '47a59529566c'
down_revision: Union[str, Sequence[str], None] = '63365882ae25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Admin dashboard access -- nobody starts as an admin (including
    # David's own account); the first one has to be flipped on directly
    # in the DB after this migration lands, same as any other one-off
    # prod data change in this project. See app/api/deps.py's
    # require_admin.
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'is_admin')
