"""add team eliminated notification type

Revision ID: d8d08426059b
Revises: 84bebf56473f
Create Date: 2026-08-13 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8d08426059b'
down_revision: Union[str, Sequence[str], None] = '84bebf56473f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same isolated ADD VALUE pattern as 9970dc56b494/84bebf56473f --
    # notificationtype is a real Postgres ENUM, no-op on SQLite.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'TEAM_ELIMINATED'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
