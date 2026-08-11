"""
Migration: add League.is_mock column.

Base.metadata.create_all() (run on every app startup) only creates missing
tables, never adds missing columns to tables that already exist. This adds
the flag POST /drafts/mock/quickstart needs to keep practice drafts out of
"my leagues" and public discovery. Safe to run repeatedly (checks first,
no-ops if already present). Works against whatever DATABASE_URL is
configured -- SQLite locally, Postgres in production.

Run once after deploying: `python migrate_add_league_is_mock.py`
"""
import asyncio
from sqlalchemy import inspect, text
from app.core.database import engine


async def migrate():
    async with engine.begin() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("leagues")}
        )
        if "is_mock" in columns:
            print("is_mock already exists on leagues — nothing to do.")
            return
        await conn.execute(text("ALTER TABLE leagues ADD COLUMN is_mock BOOLEAN NOT NULL DEFAULT FALSE"))
        print("Added is_mock to leagues.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
