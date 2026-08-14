"""make user-audit FK columns nullable for account deletion

Revision ID: 8b4e20e4d51a
Revises: 50c9bbc92165
Create Date: 2026-08-14 15:39:27.480663

Self-service account deletion (Production Quality Hardening, Phase 2)
hard-deletes the User row. Two FK columns pointing at users.id were
NOT NULL, which would block deletion via FK RESTRICT the moment the
deleted user had ever generated a digest or sent a league invite --
both of which need to survive the account that triggered them (the
digest content and the invite itself still belong to/are needed by the
league). Nulling the attribution on delete is the right behavior here,
same as league_invites.accepted_by_user_id and
league_join_requests.decided_by_user_id already being nullable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b4e20e4d51a'
down_revision: Union[str, Sequence[str], None] = '50c9bbc92165'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch_alter_table: plain ALTER COLUMN ... DROP NOT NULL doesn't
    # parse on SQLite (local dev's DB) -- batch mode recreates the table
    # there, and just proxies straight through to a normal ALTER on
    # Postgres (prod), so this is portable across both without a
    # SQLite-only branch.
    with op.batch_alter_table('commissioner_digests') as batch_op:
        batch_op.alter_column('generated_by', existing_type=sa.String(), nullable=True)
    with op.batch_alter_table('league_invites') as batch_op:
        batch_op.alter_column('invited_by_user_id', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('league_invites') as batch_op:
        batch_op.alter_column('invited_by_user_id', existing_type=sa.String(), nullable=False)
    with op.batch_alter_table('commissioner_digests') as batch_op:
        batch_op.alter_column('generated_by', existing_type=sa.String(), nullable=False)
