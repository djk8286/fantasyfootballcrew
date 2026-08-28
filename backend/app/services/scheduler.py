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
from datetime import datetime, timezone
import httpx
from sqlalchemy import select
from app.core.database import async_session
from app.services.sleeper_sync import sync_players_to_db, sync_weekly_stats, fetch_weekly_stats, SLEEPER_API
from app.services.standings_service import calculate_week, notify_matchup_results
from app.services.playoff_service import process_league_playoffs
from app.services.guillotine_service import process_league_guillotine
from app.services.best_ball_service import get_best_ball_settings, is_window_open
from app.services.waiver_service import process_league_waivers
from app.models.league import League, DraftStatus, LeagueType
from app.core.config import settings
from app.services import top_performers_service, team_recap_service, nfl_schedule_service, nfl_projections_service
from app.services.ai_service import AIService
from app.models.weekly_scores_recap import WeeklyScoresRecap

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


async def _process_all_league_guillotines_once(season: int, week: int) -> None:
    """Runs Guillotine elimination for every real, draft-completed
    GUILLOTINE league for the week that JUST ended. Elimination is
    irreversible, so -- unlike playoff advancement's repeatable
    live-week-comparison style above, which just re-checks and no-ops
    once a round is already resolved -- this must only ever act on a
    week Sleeper's own live clock has already moved past, the same
    one-time signal _notify_matchup_results_for_all_leagues_once uses.
    Called from that exact same _last_seen_week transition block, right
    before it, so a team's TEAM_ELIMINATED notification and its
    matchup-result notification land together for the same, now-settled
    week."""
    async with async_session() as db:
        result = await db.execute(select(League).where(League.league_type == LeagueType.GUILLOTINE))
        leagues = [l for l in result.scalars().all() if _league_is_auto_scorable(l)]

        processed, failed = 0, 0
        for league in leagues:
            try:
                await process_league_guillotine(league, season, week, db)
                processed += 1
            except Exception as e:
                failed += 1
                print(f"[scheduler] Guillotine processing failed for league {league.id}: {e}")

    if processed:
        print(f"[scheduler] Processed guillotine elimination for {processed} league(s), week {week} {season}" + (f", {failed} failed" if failed else ""))


# In-memory only -- see run_scheduler's call site for why that's an
# acceptable, deliberate tradeoff (a redeploy landing at the exact moment
# the live week changes just misses that one notification pass, not a
# correctness issue for anything else in this file).
_last_seen_week: tuple[int, int] | None = None

# Dashboard AI Summaries: same in-memory-only tradeoff, but tracked
# separately from _last_seen_week above -- this one updates every tick
# regardless of season_type (see _generate_nfl_wide_dashboard_summaries_once's
# docstring for why it can't share _last_seen_week's regular-season-only
# update). (season_type, season, week).
_last_seen_dashboard_week: tuple[str, int, int] | None = None

# Best-Ball (Phase 6): same in-memory-only tradeoff as _last_seen_week
# above, deliberately NOT the correctness gate itself (is_window_open is
# pure wall-clock math, recomputed fresh every tick -- a redeploy just
# means the very next closed->open transition after restart won't
# auto-fire the waiver pass, since "was_open" resets to unknown; the
# window's actual open/closed state for trade/waiver GATING is never
# affected, only this one auto-processing convenience).
_best_ball_window_state: dict[str, bool] = {}


async def _process_all_league_best_ball_window_reopens_once(now: datetime | None = None) -> None:
    """Runs every tick (like playoff processing, not gated to the
    week-transition block -- the management window can flip mid-week,
    independent of the NFL calendar). Auto-processes any queued waiver
    claims the moment a best-ball league's window transitions
    closed->open, via the exact same process_league_waivers the manual
    endpoint calls (same WAIVER_APPROVED/WAIVER_DENIED notifications,
    reviewed_by=None since there's no human actor here).

    `was_open is False` (not just falsy) deliberately excludes a
    league's first-ever observation (None) from firing -- mirrors
    _last_seen_week's own "observe, don't act, on the first tick"
    precedent, so a fresh deploy doesn't immediately fire a
    processing pass for every already-open best-ball league."""
    now = now or datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(select(League))
        leagues = [l for l in result.scalars().all() if _league_is_auto_scorable(l)]

        processed = 0
        for league in leagues:
            settings = get_best_ball_settings(league)
            if not settings["enabled"]:
                continue
            now_open = is_window_open(now, settings)
            was_open = _best_ball_window_state.get(league.id)
            _best_ball_window_state[league.id] = now_open
            if was_open is False and now_open:
                try:
                    await process_league_waivers(league, db, reviewed_by=None)
                    processed += 1
                except Exception as e:
                    print(f"[scheduler] Best-Ball auto-waiver-process failed for league {league.id}: {e}")

    if processed:
        print(f"[scheduler] Auto-processed waivers on management-window reopen for {processed} league(s)")


async def _notify_matchup_results_for_all_leagues_once(season: int, week: int) -> None:
    """Fires "you won/lost/tied your matchup" notifications for every
    real league's just-finished week. Only ever called once per week
    (see run_scheduler: triggered by the live week changing, not by
    every 2-minute tick), so this can't spam a team the way naively
    calling it on every tick would."""
    async with async_session() as db:
        result = await db.execute(select(League))
        leagues = [l for l in result.scalars().all() if _league_is_auto_scorable(l)]

        notified, failed = 0, 0
        for league in leagues:
            try:
                await notify_matchup_results(league.id, week, season, db)
                notified += 1
            except Exception as e:
                failed += 1
                print(f"[scheduler] Matchup-result notify failed for league {league.id}: {e}")

    print(f"[scheduler] Notified matchup results for {notified} league(s), week {week} {season}" + (f", {failed} failed" if failed else ""))


async def _generate_team_recaps_for_all_leagues_once(season: int, week: int) -> None:
    """Dashboard AI Summaries: auto-generates every real league's
    per-team weekly recap once a week goes final -- same one-time
    signal/call shape as the guillotine/matchup-notify passes above.
    Deliberately inside the SAME regular-season-gated week-transition
    block those use (not the separate dashboard-summaries check below)
    -- WeeklyScore rows (what this recap summarizes) only ever get
    created by _calculate_all_league_scores_once, which is itself
    gated to real regular season, so there's nothing to summarize
    outside it anyway. generate_and_save_recap no-ops (returns None)
    for a league with no scored data yet, rather than erroring."""
    async with async_session() as db:
        result = await db.execute(select(League))
        leagues = [l for l in result.scalars().all() if _league_is_auto_scorable(l)]

        generated, failed = 0, 0
        for league in leagues:
            try:
                recap = await team_recap_service.generate_and_save_recap(league, week, season, None, db)
                if recap:
                    generated += 1
            except Exception as e:
                failed += 1
                print(f"[scheduler] Team recap generation failed for league {league.id}: {e}")

    if generated or failed:
        print(f"[scheduler] Generated team recaps for {generated} league(s), week {week} {season}" + (f", {failed} failed" if failed else ""))


def _get_ai_service_for_scheduler() -> AIService:
    """Same factory ai.py/commissioner_digest_service.py/
    top_performers_service.py use -- duplicated (it's 3 lines) rather
    than shared."""
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


_ESPN_SEASON_TYPE = {"pre": 1, "regular": 2, "post": 3}


async def _generate_nfl_wide_dashboard_summaries_once(season_type: str, season: int, week: int) -> None:
    """Dashboard AI Summaries: the two NFL-wide panels (top real
    performers, NFL scores + funny recap) -- deliberately NOT gated to
    regular season the way _sync_stats_once/_calculate_all_league_scores_once
    are. That gate exists because preseason FANTASY stats are noise for
    real league SCORING; neither of these panels is fantasy scoring --
    "who had a big real game" and "what happened in real NFL games" are
    both just as real and fun to read about in preseason. Called from
    its own independent week-transition check (see run_scheduler),
    using Sleeper's live state directly rather than _last_seen_week
    (which only ever updates during regular season, since it's set from
    _sync_stats_once's return value)."""
    espn_season_type = _ESPN_SEASON_TYPE.get(season_type, 2)

    async with async_session() as db:
        try:
            await top_performers_service.generate_and_save_summary(week, season, db)
        except Exception as e:
            print(f"[scheduler] Top-performers summary generation failed: {e}")

        try:
            synced = await nfl_schedule_service.sync_week_scoreboard(season, week, espn_season_type, db)
            if synced:
                games = await nfl_schedule_service.get_week_games(season, week, espn_season_type, db)
                games_payload = [
                    {
                        "home_team_name": g.home_team_name, "home_score": g.home_score,
                        "away_team_name": g.away_team_name, "away_score": g.away_score,
                        "completed": g.completed, "status_detail": g.status_detail,
                    }
                    for g in games
                ]
                service = _get_ai_service_for_scheduler()
                content = await service.generate_nfl_scores_recap(week=week, year=season, games=games_payload)

                existing = await db.execute(
                    select(WeeklyScoresRecap).where(WeeklyScoresRecap.week == week, WeeklyScoresRecap.year == season)
                )
                recap = existing.scalar_one_or_none()
                if recap:
                    recap.content = content
                else:
                    db.add(WeeklyScoresRecap(week=week, year=season, content=content))
                await db.commit()
        except Exception as e:
            print(f"[scheduler] NFL scores recap generation failed: {e}")

    print(f"[scheduler] Generated dashboard summaries for week {week}, {season} ({season_type})")


async def _sync_players_once() -> None:
    async with async_session() as db:
        count = await sync_players_to_db(db)
    print(f"[scheduler] Synced player metadata for {count} players")


async def _sync_projections_once() -> None:
    """Sleeper's own next/current-week projection (Player.projected_stats,
    see nfl_projections_service.py) -- refreshed alongside player metadata
    (same PLAYER_SYNC_INTERVAL cadence, called right after
    _sync_players_once) since a projection is only ever useful for the
    CURRENT/UPCOMING week, unlike metadata which is always just "the
    latest snapshot" regardless of timing. Uses Sleeper's live state
    directly (season_type is one of "pre"/"regular"/"post", exactly what
    this endpoint's own path segment expects) rather than requiring
    regular season the way stats sync does -- draft prep/waiver browsing
    during the preseason is exactly when "projected points for the
    upcoming season" matters most."""
    try:
        state = await fetch_nfl_state()
        season = int(state["season"])
        week = int(state["week"])
        season_type = state.get("season_type") or "regular"
        async with async_session() as db:
            count = await nfl_projections_service.sync_week_projections(db, season, week, season_type)
        print(f"[scheduler] Synced week {week}, {season} ({season_type}) projections for {count} players")
    except Exception as e:
        print(f"[scheduler] Projections sync failed: {e}")


async def run_scheduler() -> None:
    """Entry point -- launched once as a background task at app startup
    (see main.py). Runs until cancelled at shutdown."""
    print(
        f"[scheduler] Starting -- stats every {STATS_SYNC_INTERVAL}s "
        f"(regular season only), players every {PLAYER_SYNC_INTERVAL}s"
    )
    global _last_seen_week, _last_seen_dashboard_week
    loop = asyncio.get_event_loop()
    last_player_sync = 0.0

    # Sync player metadata once immediately so a fresh deploy isn't empty;
    # don't let a failure here block the stats loop from ever starting.
    try:
        await _sync_players_once()
        last_player_sync = loop.time()
    except Exception as e:
        print(f"[scheduler] Initial player sync failed: {e}")
    await _sync_projections_once()

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
            try:
                await _process_all_league_best_ball_window_reopens_once()
            except Exception as e:
                print(f"[scheduler] Best-Ball window-reopen pass failed: {e}")

            # The live week only advances once Sleeper considers the
            # previous week's games over, so the moment it changes is our
            # only real signal that a week is "final" outside of playoffs
            # (which have their own fixed-round-vs-live-week check). Notify
            # for the week that JUST ended, using its already-scored,
            # now-final WeeklyScore rows -- not the new week, which has no
            # scores yet.
            if _last_seen_week is not None and _last_seen_week != (season, week):
                prev_season, prev_week = _last_seen_week
                try:
                    await _process_all_league_guillotines_once(prev_season, prev_week)
                except Exception as e:
                    print(f"[scheduler] Guillotine pass failed: {e}")
                try:
                    await _notify_matchup_results_for_all_leagues_once(prev_season, prev_week)
                except Exception as e:
                    print(f"[scheduler] Matchup-result notify pass failed: {e}")
                try:
                    await _generate_team_recaps_for_all_leagues_once(prev_season, prev_week)
                except Exception as e:
                    print(f"[scheduler] Team recap generation pass failed: {e}")
            _last_seen_week = (season, week)

        # Dashboard AI Summaries (NFL-wide panels): independent of the
        # regular-season-gated block above -- see
        # _generate_nfl_wide_dashboard_summaries_once's own docstring for
        # why. Own state, own live-state fetch (cheap, no-auth endpoint),
        # since _last_seen_week only ever updates when synced is not None
        # (regular season), which would silently never fire this during
        # preseason/postseason otherwise.
        try:
            state = await fetch_nfl_state()
            dash_key = (state.get("season_type"), int(state["season"]), int(state["week"]))
            if _last_seen_dashboard_week is not None and _last_seen_dashboard_week != dash_key:
                prev_type, prev_season2, prev_week2 = _last_seen_dashboard_week
                try:
                    await _generate_nfl_wide_dashboard_summaries_once(prev_type, prev_season2, prev_week2)
                except Exception as e:
                    print(f"[scheduler] Dashboard summaries pass failed: {e}")
            _last_seen_dashboard_week = dash_key
        except Exception as e:
            print(f"[scheduler] Dashboard summaries week-check failed: {e}")

        if loop.time() - last_player_sync >= PLAYER_SYNC_INTERVAL:
            try:
                await _sync_players_once()
                last_player_sync = loop.time()
            except Exception as e:
                print(f"[scheduler] Player sync iteration failed: {e}")
            await _sync_projections_once()

        await asyncio.sleep(STATS_SYNC_INTERVAL)
