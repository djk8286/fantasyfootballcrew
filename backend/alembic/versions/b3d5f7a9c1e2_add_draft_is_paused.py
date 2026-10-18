"""add drafts.is_paused

Revision ID: b3d5f7a9c1e2
Revises: a1c4e6f8b2d0
Create Date: 2026-10-18 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d5f7a9c1e2'
down_revision: Union[str, Sequence[str], None] = 'a1c4e6f8b2d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Additive: existing drafts are unpaused."""
    op.add_column('drafts', sa.Column('is_paused', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('drafts') as batch_op:
        batch_op.drop_column('is_paused')
