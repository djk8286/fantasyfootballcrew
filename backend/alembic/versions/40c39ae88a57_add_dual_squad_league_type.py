"""add dual_squad league type

Revision ID: 40c39ae88a57
Revises: 72000a537a6f
Create Date: 2026-08-13 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40c39ae88a57'
down_revision: Union[str, Sequence[str], None] = '72000a537a6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # leaguetype is a real Postgres ENUM. Same shape as 84bebf56473f
    # (GUILLOTINE) -- isolated in its own migration doing nothing else,
    # since Postgres won't let a new enum value be used in the same
    # transaction it was added in. No-op on SQLite (no real enum type
    # there).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE leaguetype ADD VALUE IF NOT EXISTS 'DUAL_SQUAD'")


def downgrade() -> None:
    """Downgrade schema."""
    pass
