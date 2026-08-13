"""add salary cap and contracts

Revision ID: 18145f6246ae
Revises: d8d08426059b
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18145f6246ae'
down_revision: Union[str, Sequence[str], None] = 'd8d08426059b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Salary-Cap + Contract Leagues (Phase 5). Plain columns/tables, no
    # enum involved anywhere -- Contract.source is a plain String
    # ("draft"/"waiver"), mirroring Draft.draft_type's own plain-String
    # precedent specifically to sidestep the enum-creation gotcha for a
    # field with only 2 values.
    op.add_column('leagues', sa.Column('salary_cap_settings', sa.JSON(), nullable=True))

    op.create_table(
        'contracts',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('league_id', sa.String(), sa.ForeignKey('leagues.id'), nullable=False),
        sa.Column('team_id', sa.String(), sa.ForeignKey('teams.id'), nullable=False),
        sa.Column('player_id', sa.String(), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('salary', sa.Float(), nullable=False),
        sa.Column('contract_years', sa.Integer(), nullable=False),
        sa.Column('signed_year', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # One ACTIVE contract per player per league -- a partial unique index
    # (Postgres: real; SQLite: also supported since 3.8, used identically
    # in tests). Mirrors uq_drafts_one_active_per_league's exact shape.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            'uq_contracts_one_active_per_league_player', 'contracts',
            ['league_id', 'player_id'], unique=True,
            postgresql_where=sa.text("is_active = true"),
        )
    else:
        op.create_index(
            'uq_contracts_one_active_per_league_player', 'contracts',
            ['league_id', 'player_id'], unique=True,
            sqlite_where=sa.text("is_active = 1"),
        )
    op.create_index('ix_contracts_league_team_active', 'contracts', ['league_id', 'team_id', 'is_active'])

    op.create_table(
        'dead_money_entries',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('league_id', sa.String(), sa.ForeignKey('leagues.id'), nullable=False),
        sa.Column('team_id', sa.String(), sa.ForeignKey('teams.id'), nullable=False),
        sa.Column('player_id', sa.String(), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('contract_id', sa.String(), sa.ForeignKey('contracts.id'), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False, server_default='early release'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('dead_money_entries')
    op.drop_index('ix_contracts_league_team_active', table_name='contracts')
    op.drop_index('uq_contracts_one_active_per_league_player', table_name='contracts')
    op.drop_table('contracts')
    op.drop_column('leagues', 'salary_cap_settings')
