"""add lineups.slots

Revision ID: b7d1e4f9a2c6
Revises: b5d1e8f2a7c3
Create Date: 2026-10-19 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d1e4f9a2c6'
down_revision: Union[str, Sequence[str], None] = 'b5d1e8f2a7c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable, no backfill: rows saved before slots get placed on read.
    op.add_column('lineups', sa.Column('slots', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('lineups', 'slots')
