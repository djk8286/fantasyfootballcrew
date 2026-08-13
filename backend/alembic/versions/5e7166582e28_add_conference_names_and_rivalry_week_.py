"""add conference names and rivalry week settings

Revision ID: 5e7166582e28
Revises: 9970dc56b494
Create Date: 2026-08-13 01:00:52.210318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e7166582e28'
down_revision: Union[str, Sequence[str], None] = '9970dc56b494'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Three plain ADD COLUMNs, no enum involved -- mirrors
    # playoff_settings' own migration shape exactly (90f2ae719677).
    #
    # Autogenerate also proposed an ALTER on notifications.type here --
    # a spurious false positive from SQLite's reflection (no native enum
    # type, so it sees the column as VARCHAR(15) and thinks it needs
    # converting to the real Postgres ENUM), not an actual pending
    # change against production. Dropped from this migration.
    op.add_column('leagues', sa.Column('conference_a_name', sa.String(), nullable=True))
    op.add_column('leagues', sa.Column('conference_b_name', sa.String(), nullable=True))
    op.add_column('leagues', sa.Column('rivalry_week_settings', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leagues', 'rivalry_week_settings')
    op.drop_column('leagues', 'conference_b_name')
    op.drop_column('leagues', 'conference_a_name')
