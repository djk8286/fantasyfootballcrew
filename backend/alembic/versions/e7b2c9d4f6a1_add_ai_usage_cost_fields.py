"""add ai usage cost fields

Revision ID: e7b2c9d4f6a1
Revises: d5e8f1a3b7c2
Create Date: 2026-10-17 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b2c9d4f6a1'
down_revision: Union[str, Sequence[str], None] = 'd5e8f1a3b7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # All nullable, no defaults -- existing rows simply have no cost data.
    op.add_column('ai_usage_events', sa.Column('model', sa.String(), nullable=True))
    op.add_column('ai_usage_events', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('ai_usage_events', sa.Column('output_tokens', sa.Integer(), nullable=True))
    op.add_column('ai_usage_events', sa.Column('cost_usd', sa.Float(), nullable=True))
    op.add_column('ai_usage_events', sa.Column('error', sa.Text(), nullable=True))
    # Daily-cost / spend-cap queries scan by created_at alone.
    op.create_index('ix_ai_usage_events_created', 'ai_usage_events', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ai_usage_events_created', table_name='ai_usage_events')
    with op.batch_alter_table('ai_usage_events') as batch_op:
        batch_op.drop_column('error')
        batch_op.drop_column('cost_usd')
        batch_op.drop_column('output_tokens')
        batch_op.drop_column('input_tokens')
        batch_op.drop_column('model')
