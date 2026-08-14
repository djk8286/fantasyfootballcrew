"""add ai commissioner settings

Revision ID: 838577fbc0ff
Revises: 6a17bf79467a
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '838577fbc0ff'
down_revision: Union[str, Sequence[str], None] = '6a17bf79467a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # AI Co-Commissioner v1 -- per-league toggle. Single plain column,
    # no enum -- bolt-on to ANY league_type, same shape every other
    # *_settings column already uses (best_ball_settings, etc.).
    op.add_column('leagues', sa.Column('ai_commissioner_settings', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leagues', 'ai_commissioner_settings')
