"""
Archive last season's aggregate stats (receptions, yards, TDs, games played,
etc.) for every player from Sleeper into Player.last_season_stats -- the
static season_points fallback shown before the new season has any real
synced data of its own (see sleeper_sync.effective_season_stats).

This does NOT touch Player.stats, which tracks the CURRENT, in-progress
season and is populated week-by-week via sync_weekly_stats once the new
season actually starts (that resets automatically at the season boundary).

Run once per year, after a season fully wraps:
`python scripts/sync_season_stats.py [season]`
Defaults to 2025 (the most recently completed season as of writing).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from app.core.database import async_session
from app.services.sleeper_sync import archive_last_season_stats

SEASON = int(sys.argv[1]) if len(sys.argv) > 1 else 2025


async def main():
    async with async_session() as db:
        count = await archive_last_season_stats(db, SEASON)
    print(f"Archived {SEASON} season stats for {count} players as the last-season reference.")


asyncio.run(main())
