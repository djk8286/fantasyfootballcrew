"""add team partner_team_id

Revision ID: 72000a537a6f
Revises: 8524e675622d
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72000a537a6f'
down_revision: Union[str, Sequence[str], None] = '8524e675622d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Dual-Squad/Mirror (Phase 7). Plain nullable self-referential column,
    # no enum involved. None = not part of a linked pair (every team
    # outside a DUAL_SQUAD league, forever); see Team.partner_team_id's
    # docstring for the symmetric-write convention.
    #
    # Gotcha (new this migration -- no prior migration added a column
    # with an inline ForeignKey): SQLite's ALTER TABLE can't add a FK
    # constraint without batch mode/table rebuild, so the column and its
    # constraint are added in two separate steps, with the real FK
    # constraint added on Postgres only.
    op.add_column('teams', sa.Column('partner_team_id', sa.String(), nullable=True))
    op.create_index('ix_teams_partner_team_id', 'teams', ['partner_team_id'])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            'fk_teams_partner_team_id', 'teams', 'teams',
            ['partner_team_id'], ['id'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint('fk_teams_partner_team_id', 'teams', type_='foreignkey')
    op.drop_index('ix_teams_partner_team_id', table_name='teams')
    op.drop_column('teams', 'partner_team_id')
