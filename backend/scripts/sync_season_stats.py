"""
Sync last season's aggregate stats (receptions, yards, TDs, games played, etc.)
for every player from Sleeper into Player.stats.

Run once after the initial player sync, and again whenever you want to
refresh season totals: `python scripts/sync_season_stats.py [season]`
Defaults to 2025 (the most recently completed season).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from app.core.database import async_session
from app.services.sleeper_sync import sync_season_stats

SEASON = sys.argv[1] if len(sys.argv) > 1 else "2025"


async def main():
    async with async_session() as db:
        count = await sync_season_stats(db, SEASON)
    print(f"Synced {SEASON} season stats for {count} players.")


asyncio.run(main())
