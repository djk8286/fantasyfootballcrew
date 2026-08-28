"""add player search_rank field

Revision ID: 63365882ae25
Revises: a492bdc047bd
Create Date: 2026-08-27 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '63365882ae25'
down_revision: Union[str, Sequence[str], None] = 'a492bdc047bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('players', sa.Column('search_rank', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('players', 'search_rank')
