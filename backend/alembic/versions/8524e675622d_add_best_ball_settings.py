"""add best ball settings

Revision ID: 8524e675622d
Revises: 18145f6246ae
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8524e675622d'
down_revision: Union[str, Sequence[str], None] = '18145f6246ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Best-Ball Hybrid (Phase 6). Single plain column, no enum -- bolt-on
    # to ANY league_type, mirrors salary_cap_settings' own shape exactly.
    op.add_column('leagues', sa.Column('best_ball_settings', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leagues', 'best_ball_settings')
