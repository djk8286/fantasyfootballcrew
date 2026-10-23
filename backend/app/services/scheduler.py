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
import json
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select
from app.core.database import async_session, background_session as draft_session
from app.services.sleeper_sync import sync_players_to_db, sync_weekly_stats, fetch_weekly_stats, rebuild_season_stats_from_weeks, SLEEPER_API
from app.services import roster_repair
from app.services.standings_service import calculate_week, notify_matchup_results, repair_default_lineup_scores
from app.services.playoff_service import process_league_playoffs
from app.services.guillotine_service import process_league_guillotine
from app.services.best_ball_service import get_best_ball_settings, is_window_open
from app.services.waiver_service import process_league_waivers
from app.services.draft_manager import advance_draft_if_due
from app.models.league import League, DraftStatus, LeagueType
from app.models.draft import Draft, DraftRunStatus
from app.core.config import settings
from app.services import top_performers_service, team_recap_service, nfl_schedule_service, nfl_projections_service, team_news_service, espn_news_service
from app.services.ai_service import AIService
from app.services.job_run_service import run_job, prune_job_runs
from app.services.nfl_state import record_nfl_state
from app.models.weekly_scores_recap import WeeklyScoresRecap
from app.models.weekly_top_players_summary import WeeklyTopPlayersSummary
from app.models.team import Team

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


NFL_STATE_PRIME_TIMEOUT = 20.0  # seconds; the startup read of /state/nfl


async def fetch_nfl_state() -> dict:
    """Sleeper's live season/week clock. Authoritative source for "what NFL
    week is it right now" -- deliberately not computed from calendar dates,
    since exact season start dates and season_type boundaries shift year to
    year and aren't worth re-deriving locally."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{SLEEPER_API}/state/nfl", timeout=15)
        response.raise_for_status()
        state = response.json()
    # Kept for GET /nfl/sync-status, so that public route never calls Sleeper.
    record_nfl_state(state)
    return state


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
    for a league with no scored data yet, rather than erroring.

    NOTE: this per-league recap is a SEPARATE feature from the NFL-wide
    Dashboard AI Summaries below (_maybe_refresh_dashboard_summaries_once)
    -- still transition-triggered/in-memory (_last_seen_week), unlike
    that one's since-fixed durable daily refresh. Not touched as part of
    that fix; flagged here in case this needs the same treatment later."""
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
    both just as real and fun to read about in preseason. Called by
    _maybe_refresh_dashboard_summaries_once's durable daily-refresh
    check below, targeting whatever week THAT determined is current --
    deliberately not using _last_seen_week itself (which only ever
    updates during regular season, since it's set from
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


DASHBOARD_SUMMARY_REFRESH_INTERVAL = timedelta(hours=24)


def _is_fresh(updated_at: datetime, now: datetime, interval: timedelta = DASHBOARD_SUMMARY_REFRESH_INTERVAL) -> bool:
    """Pure predicate pulled out of _maybe_refresh_dashboard_summaries_once/
    _maybe_refresh_team_news_once (both use this same check) specifically
    so it's unit-testable without an async DB session -- see
    test_scheduler.py's own docstring for why the rest of this file's
    async/DB/network pieces are verified manually instead. Naive
    (tzinfo-less) datetimes are treated as UTC -- SQLite drops tzinfo on
    round-trip even though every DateTime column here is declared
    timezone=True, same "assume UTC" handling this file already applies
    to Draft.current_pick_started_at in _process_expired_draft_picks_once."""
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return now - updated_at < interval


async def _maybe_refresh_dashboard_summaries_once() -> None:
    """Durable, DB-backed replacement (2026-09-22) for the old in-memory
    _last_seen_dashboard_week transition trigger. That approach only
    ever regenerated the dashboard's Top Performers/NFL Scores panels
    once, at the exact moment THIS process instance observed Sleeper's
    live week tick over -- and since the tracking lived only in memory,
    a redeploy (which this project does often) reset it. If the real
    weekly transition happened while no process instance was alive to
    observe it -- the common case on a frequently-redeployed app -- it
    was simply never caught, and these panels could sit on a stale week
    (and its now-outdated scores) indefinitely. This was the actual
    root cause of the reported "wrong weeks and scores" bug.

    Runs every scheduler tick (cheap: one no-auth Sleeper state fetch,
    one indexed DB read), and checks the DATABASE -- not memory --
    for whether the CURRENT live week's WeeklyTopPlayersSummary was
    last regenerated within DASHBOARD_SUMMARY_REFRESH_INTERVAL. Always
    targets the live CURRENT week (never "the week that just ended"),
    so even after a long gap (an outage, several redeploys in a row)
    the very next tick self-corrects to the right week on its own,
    instead of depending on catching a one-time edge trigger. content
    naturally gets richer as more of the current week's games finish --
    see TOP_PLAYERS_SUMMARY_PROMPT/NFL_SCORES_RECAP_PROMPT, both already
    written to describe "as of now" rather than assume the week is over.
    Deliberately not regular-season-gated, same reasoning
    _generate_nfl_wide_dashboard_summaries_once's own docstring gives."""
    try:
        state = await fetch_nfl_state()
        season_type = state.get("season_type") or "regular"
        season = int(state["season"])
        week = int(state["week"])
    except Exception as e:
        print(f"[scheduler] Dashboard summaries: NFL state fetch failed: {e}")
        return

    async with async_session() as db:
        result = await db.execute(
            select(WeeklyTopPlayersSummary).where(
                WeeklyTopPlayersSummary.week == week, WeeklyTopPlayersSummary.year == season,
            )
        )
        summary = result.scalar_one_or_none()

    if summary is not None and _is_fresh(summary.updated_at, datetime.now(timezone.utc)):
        return  # already refreshed within the last 24h -- nothing to do

    await _generate_nfl_wide_dashboard_summaries_once(season_type, season, week)


async def _answer_cpu_trades_once() -> int:
    from app.services.cpu_trade_service import answer_pending_cpu_trades
    async with async_session() as db:
        n = await answer_pending_cpu_trades(db)
        if n:
            await db.commit()
            print(f"[scheduler] CPU answered {n} pending trade offer(s)")
        return n


async def _maybe_refresh_team_news_once() -> None:
    """Once-daily (rolling 24h, DB-backed via TeamPlayerNews.updated_at)
    refresh of every real team's player-news digest -- see
    team_news_service.py for why this is throttled to one LLM call per
    TEAM per day rather than per player. Runs every scheduler tick; the
    24h staleness check on each team's row is what actually keeps this
    to roughly once a day, not the tick interval itself -- same
    DB-backed-not-in-memory shape as
    _maybe_refresh_dashboard_summaries_once, for the same reason (this
    self-heals across redeploys instead of depending on an in-memory
    flag surviving one). Skips mock/practice-draft leagues (is_mock)
    outright (a scratch team's news would never be seen); an empty
    roster is skipped too, both to avoid the DB round-trip and because
    generate_and_save_team_news itself also no-ops on that case."""
    async with async_session() as db:
        result = await db.execute(
            select(Team).join(League, Team.league_id == League.id).where(League.is_mock == False)  # noqa: E712
        )
        teams = result.scalars().all()

        refreshed, failed = 0, 0
        for team in teams:
            if not team.roster:
                continue
            try:
                existing = await team_news_service.get_team_news(team.id, db)
                if existing is not None and _is_fresh(existing.updated_at, datetime.now(timezone.utc)):
                    continue
                await team_news_service.generate_and_save_team_news(team, db)
                refreshed += 1
            except Exception as e:
                failed += 1
                print(f"[scheduler] Team news refresh failed for team {team.id}: {e}")

    if refreshed or failed:
        print(f"[scheduler] Refreshed player news for {refreshed} team(s)" + (f", {failed} failed" if failed else ""))


async def _repair_season_stats_once() -> None:
    async with async_session() as db:
        fixed = await rebuild_season_stats_from_weeks(db)
    print(f"[scheduler] Rebuilt season stats from weekly data for {fixed} player(s)")


async def _repair_default_lineups_once() -> None:
    async with async_session() as db:
        changes = await repair_default_lineup_scores(db)
    for c in changes:
        print(f"[scheduler] Default-lineup repair: league {c['league_id']} {c['year']} wk {c['week']} team {c['team_id']}: {c['old_total']} -> {c['new_total']}")
    print(f"[scheduler] Default-lineup repair re-scored {len(changes)} team-week(s)")


async def _repair_duplicate_rosters_once() -> None:
    async with async_session() as db:
        changes = await roster_repair.repair_duplicate_rostered_players(db)
    for c in changes:
        print(f"[scheduler] Roster repair: league {c['league_id']} player {c['player_id']} removed from team "
              f"{c['removed_from']} ({c.get('removed_from_name', '')}), kept on {c['kept_on']} ({c.get('kept_on_name', '')})")
    print(f"[scheduler] Roster repair resolved {len(changes)} duplicate roster entr{'y' if len(changes) == 1 else 'ies'}")


async def _refresh_espn_news_once() -> None:
    async with async_session() as db:
        stats = await espn_news_service.refresh_player_news(db)
    print(f"[scheduler] ESPN news: {stats['articles']} articles, {stats['added']} new player links, {stats['failed_feeds']} feed(s) failed")


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
    upcoming season" matters most.

    Raises on failure (so run_job can record it) -- see _sync_projections_safely
    for the never-raises wrapper every call site uses."""
    if not settings.SLEEPER_PROJECTIONS_ENABLED:
        return
    state = await fetch_nfl_state()
    season = int(state["season"])
    week = int(state["week"])
    season_type = state.get("season_type") or "regular"
    async with async_session() as db:
        count = await nfl_projections_service.sync_week_projections(db, season, week, season_type)
    print(f"[scheduler] Synced week {week}, {season} ({season_type}) projections for {count} players")
    # Sleeper's state week flips early in the week, but managers set next
    # week's lineup before that, so store the following week too.
    if season_type == "regular" and week < 18:
        async with async_session() as db:
            count = await nfl_projections_service.sync_week_projections(
                db, season, week + 1, season_type, update_players=False,
            )
        print(f"[scheduler] Synced week {week + 1}, {season} projections for {count} players")


async def _sync_projections_safely() -> None:
    try:
        await run_job("sync_projections", _sync_projections_once)
    except Exception as e:
        print(f"[scheduler] Projections sync failed: {e}")


async def _sync_current_week_scoreboard_once(season: int, week: int) -> None:
    """Real NFL game status (live/final/not-started) for the CURRENT
    week, refreshed every stats-sync tick (2026-09-10). Before this,
    nfl_schedule_service.sync_week_scoreboard only ever ran for the
    PREVIOUS week, once, at the moment the live week transitioned past
    it (see _generate_nfl_wide_dashboard_summaries_once below) -- fine
    for that function's own purpose (a wrap-up recap of a week that's
    already over), but useless for showing "is this player's game live
    right now" DURING the current week, which is exactly what the
    per-player score breakdown (standings.py's get_weekly_scores) needs
    to report a real LIVE/FINAL/not-started status. Same idempotent
    upsert sync_week_scoreboard already is (matches by ESPN's own
    event id), so calling it again every 2 minutes just refreshes each
    game's current state -- not a duplicate-row risk. Raises on failure
    (run_scheduler's call site catches and logs it)."""
    async with async_session() as db:
        count = await nfl_schedule_service.sync_week_scoreboard(season, week, 2, db)  # 2 = regular season, ESPN's enum
        # Next week too, so lineups for it show opponents/kickoffs and byes
        # before the live week rolls over (QA 2026-10-19: Week 7 showed "-"
        # for every game while Week 6 was still live).
        if week < 18:
            try:
                count += await nfl_schedule_service.sync_week_scoreboard(season, week + 1, 2, db)
            except Exception as e:
                await db.rollback()
                print(f"[scheduler] Next-week scoreboard sync failed: {e}")
    if count:
        print(f"[scheduler] Synced {count} live NFL game(s) for week {week}, {season}")


DRAFT_TIMER_CHECK_INTERVAL = 1  # (was 5) also drives CPU picks now -- seconds -- tight enough that a timer expiring mid-draft doesn't visibly stall
# Hard cap on one draft's pick attempt, so one stuck draft can't hold up
# the watchdog loop for every other draft.
DRAFT_PICK_ATTEMPT_TIMEOUT_S = 20


async def _process_expired_draft_picks_once() -> None:
    """Server-authoritative draft advancement -- runs whether or not any
    browser tab is open. The rules (CPU delay, autopick, pick-clock expiry,
    pause) and the double-pick guarantees live in
    draft_manager.advance_draft_if_due; this just finds in-progress drafts
    and gives each one its own session (on the dedicated background pool,
    see database.background_session), so one draft's failure -- or a busy
    request pool -- can't block the others."""
    async with draft_session() as db:
        result = await db.execute(
            select(Draft.id).where(
                Draft.status == DraftRunStatus.IN_PROGRESS,
                Draft.is_paused == False,  # noqa: E712
                Draft.current_pick_started_at.isnot(None),
            )
        )
        draft_ids = [row[0] for row in result.all()]

    forced = 0
    for draft_id in draft_ids:
        try:
            async with draft_session() as db:
                pick = await asyncio.wait_for(advance_draft_if_due(db, draft_id), DRAFT_PICK_ATTEMPT_TIMEOUT_S)
            if pick is not None:
                forced += 1
        except ValueError:
            # Lost race (a human or another worker picked first) / draft
            # finished or paused meanwhile -- nothing changed, fine.
            pass
        except Exception as e:
            print(f"[draft_timer] auto-pick failed for draft {draft_id}: {type(e).__name__}: {e}")

    if forced:
        print(f"[draft_timer] Made {forced} server-side auto-pick(s)")


async def run_draft_timer_watchdog() -> None:
    """Entry point -- launched as its own background task at app startup
    (see main.py), independent of run_scheduler's much slower stats-sync
    cadence. A draft timer can be as short as a few seconds (commissioner-
    configurable, see api_set_timer's 0-600s range), so this needs its
    own tight poll loop rather than sharing STATS_SYNC_INTERVAL's 2
    minutes."""
    print(f"[draft_timer] Starting -- checking every {DRAFT_TIMER_CHECK_INTERVAL}s for expired draft picks")
    while True:
        try:
            await run_job("draft_timer", _process_expired_draft_picks_once, record_success_every_s=60)
        except Exception as e:
            print(f"[draft_timer] Check iteration failed: {e}")
        await asyncio.sleep(DRAFT_TIMER_CHECK_INTERVAL)


async def run_scheduler() -> None:
    """Entry point -- launched once as a background task at app startup
    (see main.py). Runs until cancelled at shutdown."""
    print(
        f"[scheduler] Starting -- stats every {STATS_SYNC_INTERVAL}s "
        f"(regular season only), players every {PLAYER_SYNC_INTERVAL}s"
    )
    global _last_seen_week
    loop = asyncio.get_event_loop()
    last_player_sync = 0.0
    # Real ESPN player news (espn_news_service.py): first pass on the first
    # tick (right after the startup player sync has filled Player.espn_id),
    # then every REFRESH_INTERVAL_S. In-memory is fine here -- a redeploy
    # just means one extra polite pass.
    last_espn_news: float | None = None

    # Read Sleeper's season state first, so GET /nfl/sync-status knows the
    # season type before the slow startup syncs and repairs below finish.
    try:
        await asyncio.wait_for(fetch_nfl_state(), NFL_STATE_PRIME_TIMEOUT)
    except Exception as e:  # includes asyncio.TimeoutError
        print(f"[scheduler] Startup NFL state read failed: {type(e).__name__}: {e}")

    # Sync player metadata once immediately so a fresh deploy isn't empty;
    # don't let a failure here block the stats loop from ever starting.
    try:
        await run_job("sync_players", _sync_players_once)
        last_player_sync = loop.time()
    except Exception as e:
        print(f"[scheduler] Initial player sync failed: {e}")
    await _sync_projections_safely()

    # One-time repair of season totals inflated by the old additive weekly
    # sync (QA round 2) -- idempotent, so harmless on every later deploy.
    try:
        await run_job("repair_season_stats", _repair_season_stats_once)
    except Exception as e:
        print(f"[scheduler] Season stats repair failed: {e}")

    # One-time re-score of weeks where a team with no saved lineup scored
    # its whole roster -- idempotent (skips rows already marked with a
    # lineup_source), so harmless on every later deploy.
    try:
        await run_job("repair_default_lineups", _repair_default_lineups_once)
    except Exception as e:
        print(f"[scheduler] Default-lineup repair failed: {e}")

    # One-time cleanup of players on two rosters in a league (QA 10-19,
    # Josh Allen) -- idempotent, a no-op once none are left.
    try:
        await run_job("repair_duplicate_rosters", _repair_duplicate_rosters_once)
    except Exception as e:
        print(f"[scheduler] Duplicate-roster repair failed: {e}")

    while True:
        try:
            synced = await run_job("sync_stats", _sync_stats_once)
        except Exception as e:
            print(f"[scheduler] Stats sync iteration failed: {e}")
            await asyncio.sleep(ERROR_BACKOFF)
            continue

        if synced is not None:
            season, week = synced
            # Games first: scoring reads them for byes and kickoff state, and
            # on the tick the live week rolls over there were none yet, so
            # default lineups were built as if the schedule were unknown.
            try:
                await run_job("sync_scoreboard", _sync_current_week_scoreboard_once, season, week)
            except Exception as e:
                print(f"[scheduler] Current-week scoreboard sync pass failed: {e}")
            try:
                await run_job("calculate_scores", _calculate_all_league_scores_once, season, week)
            except Exception as e:
                # Never let an auto-score failure interrupt the sync loop
                # itself -- stats are already synced for this tick either way.
                print(f"[scheduler] Auto-score pass failed: {e}")
            try:
                await run_job("playoffs", _process_all_league_playoffs_once, season, week)
            except Exception as e:
                print(f"[scheduler] Playoff pass failed: {e}")
            try:
                await run_job("best_ball_reopen", _process_all_league_best_ball_window_reopens_once)
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
                    await run_job("guillotine", _process_all_league_guillotines_once, prev_season, prev_week)
                except Exception as e:
                    print(f"[scheduler] Guillotine pass failed: {e}")
                try:
                    await run_job("matchup_notify", _notify_matchup_results_for_all_leagues_once, prev_season, prev_week)
                except Exception as e:
                    print(f"[scheduler] Matchup-result notify pass failed: {e}")
                try:
                    await run_job("team_recaps", _generate_team_recaps_for_all_leagues_once, prev_season, prev_week)
                except Exception as e:
                    print(f"[scheduler] Team recap generation pass failed: {e}")
            _last_seen_week = (season, week)

        # CPU teams answer trade offers that were left without a reply
        # (QA 2026-10-19 LI9) -- bounded by this loop's interval.
        try:
            await run_job("cpu_trade_replies", _answer_cpu_trades_once, record_success_every_s=3600)
        except Exception as e:
            print(f"[scheduler] CPU trade reply pass failed: {e}")

        # Dashboard AI Summaries (NFL-wide panels): durable, DB-backed
        # daily refresh -- see _maybe_refresh_dashboard_summaries_once's
        # own docstring for why this replaced the old in-memory,
        # transition-triggered version (2026-09-22).
        try:
            await run_job("dashboard_summaries", _maybe_refresh_dashboard_summaries_once)
        except Exception as e:
            print(f"[scheduler] Dashboard summaries refresh check failed: {e}")

        # Real ESPN articles first, so the team digests below summarize
        # the freshest news.
        if last_espn_news is None or loop.time() - last_espn_news >= espn_news_service.REFRESH_INTERVAL_S:
            try:
                await run_job("espn_news", _refresh_espn_news_once)
            except Exception as e:
                print(f"[scheduler] ESPN news refresh failed: {e}")
            # Failure or success, wait a full interval before retrying --
            # never hammer an unofficial endpoint that's erroring.
            last_espn_news = loop.time()

        # Per-Team Player News: same durable, once-daily-via-DB-check
        # shape as the dashboard summaries refresh right above --
        # see _maybe_refresh_team_news_once's own docstring.
        try:
            await run_job("team_news", _maybe_refresh_team_news_once)
        except Exception as e:
            print(f"[scheduler] Team news refresh pass failed: {e}")

        if loop.time() - last_player_sync >= PLAYER_SYNC_INTERVAL:
            try:
                await run_job("sync_players", _sync_players_once)
                last_player_sync = loop.time()
            except Exception as e:
                print(f"[scheduler] Player sync iteration failed: {e}")
            await _sync_projections_safely()
            try:
                pruned = await run_job("prune_job_runs", prune_job_runs)
                if pruned:
                    print(f"[scheduler] Pruned {pruned} old job_runs row(s)")
            except Exception as e:
                print(f"[scheduler] job_runs prune failed: {e}")

        await asyncio.sleep(STATS_SYNC_INTERVAL)
