"""add digest tone and length

Revision ID: dd74269528b0
Revises: 8c382207a84b
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd74269528b0'
down_revision: Union[str, Sequence[str], None] = '8c382207a84b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # AI Co-Commissioner v1. Plain columns with server defaults so
    # existing rows backfill cleanly -- no enum, no FK, no SQLite
    # ALTER-add-constraint gotcha here.
    op.add_column('commissioner_digests', sa.Column('tone', sa.String(), nullable=False, server_default='professional'))
    op.add_column('commissioner_digests', sa.Column('length', sa.String(), nullable=False, server_default='full'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('commissioner_digests', 'length')
    op.drop_column('commissioner_digests', 'tone')
