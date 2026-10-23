"""
Real NFL game schedule/scores -- Dashboard AI Summaries initiative.

This app's only other external data source, Sleeper (sleeper_sync.py),
gives per-player stat lines but never a game object (no home/away
teams, no score, no kickoff time) -- confirmed by reading every
endpoint it calls. ESPN's public scoreboard endpoint fills that gap:
free, no API key, returns exactly the game-level shape needed. It's an
unofficial/undocumented endpoint (not a contracted API) -- accepted
risk for a friends-and-family beta, confirmed via AskUserQuestion.

season_type mirrors ESPN's own enum: 1=preseason, 2=regular,
3=postseason. Stored explicitly on every NFLGame row rather than
inferred, same discipline scheduler.py already applies to Sleeper
stats syncing -- a preseason Week 1 and a regular-season Week 1 must
never collide under the same (week, year) key.
"""
import asyncio
import time

import httpx
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.nfl_game import NFLGame

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# ESPN abbreviations that differ from Sleeper's. Player.team comes from
# Sleeper, so Sleeper's codes are the ones every comparison uses.
_ESPN_TO_SLEEPER = {"WSH": "WAS"}


def nfl_team_code(abbr: str) -> str:
    return _ESPN_TO_SLEEPER.get(abbr, abbr)


def as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def game_started(game: NFLGame, now: datetime) -> bool:
    """Kicked off (or past its kickoff time): players in it are locked."""
    return game.completed or game.status_state != "pre" or as_utc(game.kickoff_at) <= now


def game_teams(game: NFLGame) -> tuple[str, str]:
    """(home, away) in Player.team codes. Rows synced before codes were
    normalized at parse time still hold ESPN's, so readers go through this."""
    return nfl_team_code(game.home_team), nfl_team_code(game.away_team)


async def fetch_week_scoreboard(year: int, week: int, season_type: int) -> dict:
    """Raw ESPN scoreboard response for one (year, week, season_type).
    Query params confirmed directly against the real endpoint -- `year`
    is the season label ESPN expects (not necessarily identical to what
    it echoes back in the response body; always trust the response's
    own `season`/`week` fields over what was requested, see
    sync_week_scoreboard below)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            ESPN_SCOREBOARD_URL, params={"year": year, "seasontype": season_type, "week": week}
        )
        response.raise_for_status()
        return response.json()


def _parse_event(event: dict) -> dict | None:
    """One ESPN scoreboard `events[]` entry -> our flat NFLGame shape.
    Returns None if the event doesn't have the expected two-competitor
    shape (defensive -- an unofficial API earns defensive parsing, not
    an assumption every field is always present)."""
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competitors = competitions[0].get("competitors") or []
    if len(competitors) != 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    status = event.get("status", {}).get("type", {})
    state = status.get("state", "pre")
    completed = bool(status.get("completed", False))

    def _score(c: dict) -> int | None:
        # ESPN sends "0" for games that haven't been played, including
        # postponed and canceled ones. That's no score, not a 0-0 game.
        if not completed and state != "in":
            return None
        raw = c.get("score")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "espn_event_id": str(event["id"]),
        "home_team": nfl_team_code(home["team"].get("abbreviation", "??")),
        "home_team_name": home["team"].get("displayName", "Unknown"),
        "home_score": _score(home),
        "away_team": nfl_team_code(away["team"].get("abbreviation", "??")),
        "away_team_name": away["team"].get("displayName", "Unknown"),
        "away_score": _score(away),
        "status_state": state,
        "status_detail": status.get("shortDetail", ""),
        "completed": completed,
        "kickoff_at": datetime.fromisoformat(event["date"].replace("Z", "+00:00")),
    }


async def sync_week_scoreboard(year: int, week: int, season_type: int, db: AsyncSession) -> int:
    """Fetch + upsert every game for one week. Trusts ESPN's own
    response `season`/`week` fields for what actually gets stored
    (not blindly the requested params -- a request quirk observed
    directly: passing year=2025 echoed back season.year=2026 for the
    same real games, so the response is the source of truth, the
    request params are just "which week to fetch")."""
    data = await fetch_week_scoreboard(year, week, season_type)
    return await store_week_scoreboard(data, year, week, season_type, db)


async def store_week_scoreboard(data: dict, year: int, week: int, season_type: int, db: AsyncSession) -> int:
    """Upsert one ESPN scoreboard response (see sync_week_scoreboard)."""
    resolved_year = data.get("season", {}).get("year", year)
    resolved_week = data.get("week", {}).get("number", week)
    resolved_season_type = data.get("season", {}).get("type", season_type)

    synced = 0
    for event in data.get("events", []):
        parsed = _parse_event(event)
        if not parsed:
            continue
        result = await db.execute(
            select(NFLGame).where(NFLGame.espn_event_id == parsed["espn_event_id"])
        )
        existing = result.scalar_one_or_none()
        if existing:
            for key, value in parsed.items():
                setattr(existing, key, value)
            existing.week = resolved_week
            existing.year = resolved_year
            existing.season_type = resolved_season_type
        else:
            db.add(NFLGame(
                week=resolved_week, year=resolved_year, season_type=resolved_season_type, **parsed,
            ))
        synced += 1

    await db.commit()
    return synced


# (year, week, season_type) -> monotonic time of the last on-demand fetch,
# so a week ESPN has nothing for isn't refetched on every page load.
_ensure_attempts: dict[tuple[int, int, int], float] = {}
ENSURE_RETRY_S = 600.0
# Tests turn this off (conftest) so no test reaches ESPN.
ON_DEMAND_SYNC = True


async def ensure_week_games(year: int, week: int, season_type: int, db: AsyncSession) -> list[NFLGame]:
    """get_week_games, syncing the week from ESPN first if nothing is stored.

    The scheduler only syncs the live week (and the next one), so a lineup
    opened for any other week used to find no games: every GAME cell showed
    "-" and nobody counted as on bye. A failed or empty fetch is retried at
    most every ENSURE_RETRY_S; errors are swallowed (the page still works,
    just without game info)."""
    games = await get_week_games(year, week, season_type, db)
    if games or not ON_DEMAND_SYNC or not (1 <= week <= 18):
        return games
    key = (year, week, season_type)
    now = time.monotonic()
    last = _ensure_attempts.get(key)
    if last is not None and now - last < ENSURE_RETRY_S:
        return games
    _ensure_attempts[key] = now
    try:
        data = await asyncio.wait_for(fetch_week_scoreboard(year, week, season_type), timeout=20)
    except Exception as e:  # network/ESPN failure: show the page without games
        print(f"[nfl_schedule] on-demand fetch of {year} week {week} failed: {e}")
        return games
    resolved = data.get("week", {}).get("number", week)
    if resolved != week:
        # ESPN answered with a different week; store nothing under the wrong number.
        return games
    await store_week_scoreboard(data, year, week, season_type, db)
    return await get_week_games(year, week, season_type, db)


async def get_week_games(year: int, week: int, season_type: int, db: AsyncSession) -> list[NFLGame]:
    result = await db.execute(
        select(NFLGame).where(
            NFLGame.year == year, NFLGame.week == week, NFLGame.season_type == season_type,
        ).order_by(NFLGame.kickoff_at)
    )
    return list(result.scalars().all())
