"""add player projected stats fields

Revision ID: a492bdc047bd
Revises: f862312d035b
Create Date: 2026-08-27 20:33:28.806098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a492bdc047bd'
down_revision: Union[str, Sequence[str], None] = 'f862312d035b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('players', sa.Column('projected_stats', sa.JSON(), nullable=True))
    op.add_column('players', sa.Column('projected_week', sa.Integer(), nullable=True))
    op.add_column('players', sa.Column('projected_year', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('players', 'projected_year')
    op.drop_column('players', 'projected_week')
    op.drop_column('players', 'projected_stats')
