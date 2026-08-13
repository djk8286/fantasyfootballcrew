"""add team elimination columns

Revision ID: a673090b8698
Revises: 5e7166582e28
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a673090b8698'
down_revision: Union[str, Sequence[str], None] = '5e7166582e28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Guillotine (Phase 4). Plain columns, no enum involved -- mirrors
    # 5e7166582e28's own shape exactly. None/nullable = alive/no last
    # words yet; see Team.eliminated_week's docstring for why there's no
    # separate boolean.
    op.add_column('teams', sa.Column('eliminated_week', sa.Integer(), nullable=True))
    op.add_column('teams', sa.Column('last_words', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('teams', 'last_words')
    op.drop_column('teams', 'eliminated_week')
