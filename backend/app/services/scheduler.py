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

Immediately after each successful stats sync, this also recalculates
WeeklyScore for every real league at the live NFL week -- previously
POST /standings/calculate was the *only* way scores ever got computed,
meaning a commissioner had to remember to click it every single week or
standings just silently went stale. There's no per-league "current week"
concept anywhere in this app (League has no such field, and the
round-robin schedule/season-schedule code already key everything off a
plain week/year) -- every league just follows the one real NFL calendar,
so the same (season, week) this sync just fetched applies to all of them.
The manual commissioner button still exists unchanged, as a force-recalc
option (e.g. after a late roster correction).
"""
import asyncio
import httpx
from sqlalchemy import select
from app.core.database import async_session
from app.services.sleeper_sync import sync_players_to_db, sync_weekly_stats, fetch_weekly_stats, SLEEPER_API
from app.services.standings_service import calculate_week
from app.services.playoff_service import process_league_playoffs
from app.models.league import League, DraftStatus

PLAYER_SYNC_INTERVAL = 60 * 60  # 1 hour -- injury designations/roster moves change closer to gameday than the rest of a player's metadata
STATS_SYNC_INTERVAL = 2 * 60    # 2 minutes -- as live as practical without hammering Sleeper's free API
ERROR_BACKOFF = 60              # after a failed iteration, wait this long before the next attempt


def _league_is_auto_scorable(league: League) -> bool:
    """Mock/practice-draft leagues (is_mock) are scratch data that never
    belongs in real standings, and a league whose draft hasn't finished
    doesn't have real rosters yet -- scoring it would just be scoring
    mostly-empty teams. Pulled out as its own function so this policy is
    unit-testable without a database."""
    return not league.is_mock and league.draft_status == DraftStatus.COMPLETED


async def fetch_nfl_state() -> dict:
    """Sleeper's live season/week clock. Authoritative source for "what NFL
    week is it right now" -- deliberately not computed from calendar dates,
    since exact season start dates and season_type boundaries shift year to
    year and aren't worth re-deriving locally."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{SLEEPER_API}/state/nfl", timeout=15)
        response.raise_for_status()
        return response.json()


async def _sync_stats_once() -> tuple[int, int] | None:
    """Returns the (season, week) just synced, or None if this tick was
    skipped (not regular season) -- callers use this to know whether
    there's a current week to auto-score against."""
    state = await fetch_nfl_state()
    season_type = state.get("season_type")
    if season_type != "regular":
        print(f"[scheduler] Skipping stats sync -- season_type={season_type!r} (not regular season yet)")
        return None

    season = int(state["season"])
    week = int(state["week"])
    async with async_session() as db:
        count = await sync_weekly_stats(db, season, week)
    print(f"[scheduler] Synced week {week}, {season} stats for {count} players")
    return season, week


async def _calculate_all_league_scores_once(season: int, week: int) -> None:
    """Recalculate WeeklyScore for every real, draft-completed league at
    (season, week). One Sleeper fetch shared across every league rather
    than each league re-fetching the identical payload (calculate_week's
    sleeper_stats param exists specifically for this). Each league is
    wrapped individually so one league's bad data (e.g. a malformed
    roster) can't take the rest of the pass down with it."""
    try:
        sleeper_stats = await fetch_weekly_stats(season, week)
    except Exception as e:
        print(f"[scheduler] Auto-score pass skipped -- stats fetch failed: {e}")
        return

    async with async_session() as db:
        result = await db.execute(select(League))
        leagues = [l for l in result.scalars().all() if _league_is_auto_scorable(l)]

        scored, failed = 0, 0
        for league in leagues:
            try:
                await calculate_week(league.id, week, season, db, sleeper_stats=sleeper_stats)
                scored += 1
            except Exception as e:
                failed += 1
                print(f"[scheduler] Auto-score failed for league {league.id}: {e}")

    print(f"[scheduler] Auto-scored week {week}, {season} for {scored} league(s)" + (f", {failed} failed" if failed else ""))


async def _process_all_league_playoffs_once(season: int, week: int) -> None:
    """Generates/advances playoff brackets for every real, draft-completed,
    playoff-ENABLED league (most leagues have it off by default, and
    process_league_playoffs itself no-ops for those -- this only exists
    as a separate pass from the scoring one above so a playoff-generation
    bug can't affect regular scoring, and vice versa). Called with the
    same (season, week) _calculate_all_league_scores_once just used, so
    playoff advancement always sees this tick's freshly-committed
    WeeklyScore rows, not a stale read from before scoring ran."""
    async with async_session() as db:
        result = await db.execute(select(League))
        leagues = [l for l in result.scalars().all() if _league_is_auto_scorable(l)]

        processed, failed = 0, 0
        for league in leagues:
            try:
                await process_league_playoffs(league, season, week, db)
                processed += 1
            except Exception as e:
                failed += 1
                print(f"[scheduler] Playoff processing failed for league {league.id}: {e}")

    if processed:
        print(f"[scheduler] Processed playoffs for {processed} league(s)" + (f", {failed} failed" if failed else ""))


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
            synced = await _sync_stats_once()
        except Exception as e:
            print(f"[scheduler] Stats sync iteration failed: {e}")
            await asyncio.sleep(ERROR_BACKOFF)
            continue

        if synced is not None:
            season, week = synced
            try:
                await _calculate_all_league_scores_once(season, week)
            except Exception as e:
                # Never let an auto-score failure interrupt the sync loop
                # itself -- stats are already synced for this tick either way.
                print(f"[scheduler] Auto-score pass failed: {e}")
            try:
                await _process_all_league_playoffs_once(season, week)
            except Exception as e:
                print(f"[scheduler] Playoff pass failed: {e}")

        if loop.time() - last_player_sync >= PLAYER_SYNC_INTERVAL:
            try:
                await _sync_players_once()
                last_player_sync = loop.time()
            except Exception as e:
                print(f"[scheduler] Player sync iteration failed: {e}")

        await asyncio.sleep(STATS_SYNC_INTERVAL)
