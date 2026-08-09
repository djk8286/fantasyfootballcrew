"""
Migration: add Team.conference column.

Base.metadata.create_all() (run on every app startup) only creates missing
tables, never adds missing columns to tables that already exist. This adds
the one column conference-league standings need, safely (checks first,
no-ops if already present). Works against whatever DATABASE_URL is
configured -- SQLite locally, Postgres in production.

Run once after deploying: `python migrate_add_team_conference.py`
"""
import asyncio
from sqlalchemy import inspect, text
from app.core.database import engine


async def migrate():
    async with engine.begin() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("teams")}
        )
        if "conference" in columns:
            print("conference already exists on teams — nothing to do.")
            return
        await conn.execute(text("ALTER TABLE teams ADD COLUMN conference VARCHAR"))
        print("Added conference to teams.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
