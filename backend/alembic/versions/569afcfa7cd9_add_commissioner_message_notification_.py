"""add commissioner_message notification type

Revision ID: 569afcfa7cd9
Revises: dd74269528b0
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '569afcfa7cd9'
down_revision: Union[str, Sequence[str], None] = 'dd74269528b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same isolated ADD VALUE pattern as d8d08426059b/9970dc56b494 --
    # notificationtype is a real Postgres ENUM, no-op on SQLite. Backs
    # AI Co-Commissioner v1 Phase 2's Communication Helpers -- a
    # commissioner-drafted-and-sent broadcast delivered via
    # notify_league_teams.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'COMMISSIONER_MESSAGE'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
