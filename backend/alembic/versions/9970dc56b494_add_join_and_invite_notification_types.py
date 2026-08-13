"""add join and invite notification types

Revision ID: 9970dc56b494
Revises: b136ce50878b
Create Date: 2026-08-12 23:22:28.934687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9970dc56b494'
down_revision: Union[str, Sequence[str], None] = 'b136ce50878b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_VALUES = ["LEAGUE_INVITE_ACCEPTED", "JOIN_REQUEST_RECEIVED", "JOIN_REQUEST_DECIDED"]


def upgrade() -> None:
    """Upgrade schema."""
    # notificationtype is a real Postgres ENUM (see ff739e020b40). Adding
    # values needs ALTER TYPE ... ADD VALUE, which Alembic's autogenerate
    # doesn't produce -- this migration is hand-written, not generated.
    # Stored as the Python enum's .name (uppercase), not .value, matching
    # how ff739e020b40 listed the existing members -- SQLAlchemy's
    # Enum(NotificationType) defaults to .name for storage.
    #
    # SQLite (local dev) has no real enum type -- Enum columns are just a
    # VARCHAR with no server-side CHECK, so there's nothing to alter and
    # this is a no-op there. Only run the ALTER TYPE on Postgres.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in NEW_VALUES:
            # Each ADD VALUE must run in its own statement outside any
            # other DDL in the same migration (Postgres won't let a new
            # enum value be used in the same transaction it was added in,
            # and won't allow combining multiple ADD VALUEs cleanly with
            # other schema changes) -- this migration does nothing else,
            # by design, to keep that isolated.
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no ALTER TYPE ... DROP VALUE -- removing an enum value
    # requires rebuilding the type (create new type, migrate the column,
    # drop old type), which is real effort for a downgrade path this
    # project has never needed in practice. No-op, same reasoning as
    # every other additive-only enum migration here.
    pass
