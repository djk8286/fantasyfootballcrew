"""add job runs

Revision ID: c41a7e2b9d10
Revises: 9a4d2e6c81f5
Create Date: 2026-10-17 21:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41a7e2b9d10'
down_revision: Union[str, Sequence[str], None] = '9a4d2e6c81f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # New table only -- purely additive, no existing data touched.
    op.create_table('job_runs',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('job_name', sa.String(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_job_runs_job_started', 'job_runs', ['job_name', 'started_at'], unique=False)
    op.create_index('ix_job_runs_started', 'job_runs', ['started_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_job_runs_started', table_name='job_runs')
    op.drop_index('ix_job_runs_job_started', table_name='job_runs')
    op.drop_table('job_runs')
