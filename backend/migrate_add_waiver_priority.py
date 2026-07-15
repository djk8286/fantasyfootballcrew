"""
Migration: add League.waiver_priority column.

Base.metadata.create_all() (run on every app startup) only creates missing
tables, never adds missing columns to tables that already exist. This adds
the one column this session's work needs, safely (checks first, no-ops if
already present). Works against whatever DATABASE_URL is configured —
SQLite locally, Postgres in production.

Run once after deploying: `python migrate_add_waiver_priority.py`
"""
import asyncio
from sqlalchemy import inspect, text
from app.core.database import engine


async def migrate():
    async with engine.begin() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("leagues")}
        )
        if "waiver_priority" in columns:
            print("waiver_priority already exists on leagues — nothing to do.")
            return
        await conn.execute(text("ALTER TABLE leagues ADD COLUMN waiver_priority JSON"))
        print("Added waiver_priority to leagues.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
