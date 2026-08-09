"""
Migration: add Player.stats_year, Player.last_season_stats,
Player.last_season_year columns.

Base.metadata.create_all() (run on every app startup) only creates missing
tables, never adds missing columns to tables that already exist. These
three columns back season_points' current-season-vs-last-season fallback
(see sleeper_sync.effective_season_stats) -- without stats_year, Player.stats
has no way to know which season it actually represents, and without
last_season_stats, there's nothing to fall back to before the new season
has real synced data. Safe to run repeatedly (checks first, no-ops if
already present). Works against whatever DATABASE_URL is configured --
SQLite locally, Postgres in production.

Run once after deploying: `python migrate_add_player_season_fields.py`
"""
import asyncio
from sqlalchemy import inspect, text
from app.core.database import engine


COLUMNS = {
    "stats_year": "INTEGER",
    "last_season_stats": "JSON",
    "last_season_year": "INTEGER",
}


async def migrate():
    async with engine.begin() as conn:
        existing = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("players")}
        )
        for name, sql_type in COLUMNS.items():
            if name in existing:
                print(f"{name} already exists on players — skipping.")
                continue
            await conn.execute(text(f"ALTER TABLE players ADD COLUMN {name} {sql_type}"))
            print(f"Added {name} to players.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
