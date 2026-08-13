"""add guillotine league type

Revision ID: 84bebf56473f
Revises: a673090b8698
Create Date: 2026-08-13 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84bebf56473f'
down_revision: Union[str, Sequence[str], None] = 'a673090b8698'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # leaguetype is a real Postgres ENUM (see f8b382aa77e8). Adding a
    # value needs ALTER TYPE ... ADD VALUE, which Alembic's autogenerate
    # doesn't produce -- hand-written, same shape as 9970dc56b494. Stored
    # as the Python enum's .name (uppercase), matching how the existing
    # STANDARD/TWO_MAN/CONFERENCE members are stored.
    #
    # SQLite (local dev) has no real enum type -- nothing to alter there,
    # so this is a no-op outside Postgres. Isolated in its own migration,
    # doing nothing else, since Postgres won't let a new enum value be
    # used in the same transaction it was added in.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE leaguetype ADD VALUE IF NOT EXISTS 'GUILLOTINE'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no ALTER TYPE ... DROP VALUE -- same no-op reasoning
    # as every other additive-only enum migration in this project.
    pass
