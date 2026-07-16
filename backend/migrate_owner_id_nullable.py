"""
Migration: make Team.owner_id nullable.

CPU teams used to be given the sentinel owner_id="cpu", but owner_id is a
foreign key to users.id — SQLite silently ignores FK violations by default,
but Postgres enforces them, so every CPU-team bulk-add crashed in production.
Fix: owner_id is now nullable and CPU teams get owner_id=None. This migration
relaxes the constraint on a teams table that already exists with the old
NOT NULL definition (Base.metadata.create_all() never alters existing
columns, only creates missing tables).

Postgres-only (uses ALTER COLUMN, which SQLite doesn't support) — but SQLite
never enforced this constraint anyway, so there's nothing to migrate there.

Run once against production: `python migrate_owner_id_nullable.py`
"""
import asyncio
from sqlalchemy import inspect, text
from app.core.database import engine


async def migrate():
    async with engine.begin() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"]: c for c in inspect(sync_conn).get_columns("teams")}
        )
        owner_id_col = columns.get("owner_id")
        if owner_id_col is None:
            print("teams.owner_id column not found — nothing to do.")
            return
        if owner_id_col["nullable"]:
            print("teams.owner_id is already nullable — nothing to do.")
            return
        await conn.execute(text("ALTER TABLE teams ALTER COLUMN owner_id DROP NOT NULL"))
        print("Dropped NOT NULL constraint on teams.owner_id.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
