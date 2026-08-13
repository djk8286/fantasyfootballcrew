"""add league visibility

Revision ID: 3fe38bc9ecc9
Revises: 90f2ae719677
Create Date: 2026-08-12 21:07:34.422063

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3fe38bc9ecc9'
down_revision: Union[str, Sequence[str], None] = '90f2ae719677'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


league_visibility_enum = sa.Enum('PRIVATE', 'INVITE_ONLY', 'OPEN', name='leaguevisibility')


def upgrade() -> None:
    """Upgrade schema."""
    # Confirmed the hard way against production (first attempt at this
    # migration failed with `type "leaguevisibility" does not exist`):
    # unlike CREATE TABLE, where SQLAlchemy's Postgres DDL compiler
    # auto-emits CREATE TYPE for an inline Enum column, ALTER TABLE ADD
    # COLUMN does NOT -- the enum type has to be created explicitly first.
    # SQLite has no native enum type at all (CHECK constraint instead), so
    # this passed clean locally and only broke for real on Postgres.
    # checkfirst=True makes this safe to re-run.
    bind = op.get_bind()
    league_visibility_enum.create(bind, checkfirst=True)

    # server_default is required here (autogenerate doesn't add one on its
    # own) -- these are NOT NULL columns being added to the existing
    # `leagues` table, which already has real rows in production. Without
    # a server-side default, ALTER TABLE ADD COLUMN NOT NULL fails outright
    # against any table with existing data. 'OPEN'/false match the model's
    # Python-level defaults (League.visibility/wanted_board_hidden) --
    # every pre-existing league keeps behaving exactly as "Open, not
    # hidden" until a commissioner deliberately changes it.
    op.add_column('leagues', sa.Column('visibility', league_visibility_enum, nullable=False, server_default='OPEN'))
    op.add_column('leagues', sa.Column('wanted_board_hidden', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('leagues', 'wanted_board_hidden')
    op.drop_column('leagues', 'visibility')
    bind = op.get_bind()
    league_visibility_enum.drop(bind, checkfirst=True)
