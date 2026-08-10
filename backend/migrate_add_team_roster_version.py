"""
Migration: add Team.roster_version column.

Base.metadata.create_all() (run on every app startup) only creates missing
tables, never adds missing columns to tables that already exist. This adds
the compare-and-swap counter commissioner.review_trade needs to detect a
roster that changed under it between read and write (two trades touching
the same team, approved concurrently, used to silently lose one trade's
player movement -- see the comment above the CAS in review_trade). Safe to
run repeatedly (checks first, no-ops if already present). Works against
whatever DATABASE_URL is configured -- SQLite locally, Postgres in
production.

Run once after deploying: `python migrate_add_team_roster_version.py`
"""
import asyncio
from sqlalchemy import inspect, text
from app.core.database import engine


async def migrate():
    async with engine.begin() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("teams")}
        )
        if "roster_version" in columns:
            print("roster_version already exists on teams — nothing to do.")
            return
        await conn.execute(text("ALTER TABLE teams ADD COLUMN roster_version INTEGER NOT NULL DEFAULT 0"))
        print("Added roster_version to teams.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
