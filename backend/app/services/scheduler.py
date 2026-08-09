"""
Background sync scheduler.

Runs as an asyncio task for the lifetime of the app process (started from
main.py's lifespan), keeping player metadata and live stats current
without a manual trigger or external cron. Two independent cadences:

- Player metadata (name/team/injury status/position) via
  sync_players_to_db -- every PLAYER_SYNC_INTERVAL, regardless of time of
  year, since injuries/roster moves/trades matter even in the offseason.

- Current-week stats via sync_weekly_stats -- every STATS_SYNC_INTERVAL,
  but ONLY once Sleeper's live /state/nfl reports season_type == "regular".
  This is deliberate, not just an optimization: preseason stats are noise
  for real fantasy scoring, and syncing them would be actively harmful --
  sync_weekly_stats only resets Player.stats when the *year* changes, not
  the season_type, so a preseason sync tagged season=2026 would silently
  blend into the real week 1 (also season=2026) once it arrives, instead
  of starting clean. Skipping preseason/offseason entirely means
  Player.stats stays empty until real regular-season data exists, which is
  exactly what effective_season_stats' last-season fallback is built to
  detect (see sleeper_sync.py).
"""
import asyncio
import httpx
from app.core.database import async_session
from app.services.sleeper_sync import sync_players_to_db, sync_weekly_stats, SLEEPER_API

PLAYER_SYNC_INTERVAL = 60 * 60  # 1 hour -- injury designations/roster moves change closer to gameday than the rest of a player's metadata
STATS_SYNC_INTERVAL = 2 * 60    # 2 minutes -- as live as practical without hammering Sleeper's free API
ERROR_BACKOFF = 60              # after a failed iteration, wait this long before the next attempt


async def fetch_nfl_state() -> dict:
    """Sleeper's live season/week clock. Authoritative source for "what NFL
    week is it right now" -- deliberately not computed from calendar dates,
    since exact season start dates and season_type boundaries shift year to
    year and aren't worth re-deriving locally."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{SLEEPER_API}/state/nfl", timeout=15)
        response.raise_for_status()
        return response.json()


async def _sync_stats_once() -> None:
    state = await fetch_nfl_state()
    season_type = state.get("season_type")
    if season_type != "regular":
        print(f"[scheduler] Skipping stats sync -- season_type={season_type!r} (not regular season yet)")
        return

    season = int(state["season"])
    week = int(state["week"])
    async with async_session() as db:
        count = await sync_weekly_stats(db, season, week)
    print(f"[scheduler] Synced week {week}, {season} stats for {count} players")


async def _sync_players_once() -> None:
    async with async_session() as db:
        count = await sync_players_to_db(db)
    print(f"[scheduler] Synced player metadata for {count} players")


async def run_scheduler() -> None:
    """Entry point -- launched once as a background task at app startup
    (see main.py). Runs until cancelled at shutdown."""
    print(
        f"[scheduler] Starting -- stats every {STATS_SYNC_INTERVAL}s "
        f"(regular season only), players every {PLAYER_SYNC_INTERVAL}s"
    )
    loop = asyncio.get_event_loop()
    last_player_sync = 0.0

    # Sync player metadata once immediately so a fresh deploy isn't empty;
    # don't let a failure here block the stats loop from ever starting.
    try:
        await _sync_players_once()
        last_player_sync = loop.time()
    except Exception as e:
        print(f"[scheduler] Initial player sync failed: {e}")

    while True:
        try:
            await _sync_stats_once()
        except Exception as e:
            print(f"[scheduler] Stats sync iteration failed: {e}")
            await asyncio.sleep(ERROR_BACKOFF)
            continue

        if loop.time() - last_player_sync >= PLAYER_SYNC_INTERVAL:
            try:
                await _sync_players_once()
                last_player_sync = loop.time()
            except Exception as e:
                print(f"[scheduler] Player sync iteration failed: {e}")

        await asyncio.sleep(STATS_SYNC_INTERVAL)
