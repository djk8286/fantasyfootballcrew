"""mark voided waiver claims denied

Roster repair used to leave a voided waiver claim APPROVED with the reason
in details.voided. It now marks them DENIED. This brings the older rows in
line so every voided claim reads as denied.

Revision ID: d4f2b9c1e6a3
Revises: c3e8a1d5f7b2
Create Date: 2026-10-22 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4f2b9c1e6a3'
down_revision: Union[str, Sequence[str], None] = 'c3e8a1d5f7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum columns store the member name, so the values are upper case.
    # details is JSON (not JSONB) on Postgres. ->> works on both, and on SQLite 3.38+.
    op.execute(
        "UPDATE transactions SET status = 'DENIED' "
        "WHERE type = 'WAIVER' AND status = 'APPROVED' AND details->>'voided' IS NOT NULL"
    )


def downgrade() -> None:
    # No-op. Rows denied here can't be told apart from ones roster repair
    # denied directly, and a voided claim shouldn't read approved anyway.
    pass
