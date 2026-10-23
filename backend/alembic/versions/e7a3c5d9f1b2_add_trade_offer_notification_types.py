"""add trade_offer and trade_accepted notification types

Revision ID: e7a3c5d9f1b2
Revises: d4f2b9c1e6a3
Create Date: 2026-10-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e7a3c5d9f1b2'
down_revision: Union[str, Sequence[str], None] = 'd4f2b9c1e6a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Same ADD VALUE pattern as 569afcfa7cd9. notificationtype is a real
    # Postgres ENUM stored by name, so the values are upper case. No-op on
    # SQLite. TRADE_OFFER tells a human team it has an offer to answer.
    # TRADE_ACCEPTED tells the proposer and commissioners it was accepted.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'TRADE_OFFER'")
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'TRADE_ACCEPTED'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres can't drop an enum value. The extra values are harmless to
    # older code, which never writes them.
    pass
