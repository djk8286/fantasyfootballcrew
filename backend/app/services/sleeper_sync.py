"""
Sleeper API Sync Service

Fetches NFL player data from the Sleeper API and syncs it to our database.
Sleeper API is free with no auth key required for read access.

Endpoints used:
- https://api.sleeper.app/v1/players/nfl - Full NFL player list
- https://api.sleeper.app/v1/players/{player_id} - Individual player
- https://api.sleeper.app/v1/stats/nfl/{year} - Season stats
- https://api.sleeper.app/v1/stats/nfl/{year}/{week} - Weekly stats
"""

import httpx
from datetime import date
from typing import Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.player import Player


SLEEPER_API = "https://api.sleeper.app/v1"


def current_nfl_season_year(today: Optional[date] = None) -> int:
    """The NFL season is named for the year it starts in and runs into the
    following spring, so from January through August we're still in the
    PREVIOUS year's season for fantasy purposes (e.g. a game in Feb 2026
    belongs to the 2025 season; the 2026 season doesn't start until
    September). Used to decide whether Player.stats holds real current-
    season data yet or should fall back to last_season_stats."""
    today = today or date.today()
    return today.year if today.month >= 9 else today.year - 1


def effective_season_stats(player: Player) -> Tuple[Dict[str, Any], Optional[int]]:
    """Which stats blob season_points should be computed from, and which
    year it represents: the current season's live data if the season has
    actually started AND we've synced something for it, otherwise last
    season's archived totals as a reference. Returns (stats, year) so
    callers can label which one they got (e.g. "2025 Season" vs
    "2026 Season") rather than presenting a stale number as if it were
    live."""
    if player.stats_year == current_nfl_season_year() and player.stats:
        return player.stats, player.stats_year
    return (player.last_season_stats or {}), player.last_season_year


async def fetch_all_players() -> Dict[str, Any]:
    """Fetch all NFL players from Sleeper API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{SLEEPER_API}/players/nfl")
        response.raise_for_status()
        return response.json()


async def sync_players_to_db(db: AsyncSession) -> int:
    """Fetch all NFL players from Sleeper and sync to local database.
    Returns the count of players synced."""
    players_data = await fetch_all_players()
    count = 0

    for sleeper_id, data in players_data.items():
        # Skip non-NFL players or incomplete data. Sleeper's payload includes
        # junk placeholder entries (e.g. "Duplicate Player") with no position;
        # `position` is required (NOT NULL), so these must be filtered here
        # rather than relying on a .get(..., "UNKNOWN") default, which only
        # applies when the key is absent -- not when it's present and null.
        if not data.get("first_name") or not data.get("last_name") or not data.get("position"):
            continue

        # Check if player already exists
        result = await db.execute(
            select(Player).where(Player.sleeper_id == sleeper_id)
        )
        existing = result.scalar_one_or_none()

        # Sleeper's own overall fantasy-relevance rank (lower = better) --
        # see Player.search_rank. Unconditional overwrite (not "or existing
        # value" like team/injury_status above) since this is meant to
        # track Sleeper's current live number exactly, including it going
        # away (None) if Sleeper ever stops ranking a player who used to
        # have one -- there's no "keep the last known value" case that
        # makes sense for a rank the way there is for e.g. team.
        search_rank = data.get("search_rank")

        if existing:
            # Update existing player
            existing.team = data.get("team") or existing.team
            existing.injury_status = data.get("injury_status") or existing.injury_status
            existing.bye_week = data.get("bye_week") or existing.bye_week
            if data.get("fantasy_positions"):
                existing.fantasy_positions = data["fantasy_positions"]
            existing.search_rank = search_rank
        else:
            # Create new player
            player = Player(
                sleeper_id=sleeper_id,
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                position=data.get("position", "UNKNOWN"),
                team=data.get("team"),
                bye_week=data.get("bye_week"),
                injury_status=data.get("injury_status"),
                fantasy_positions=data.get("fantasy_positions"),
                age=data.get("age"),
                number=data.get("number"),
                search_rank=search_rank,
            )
            db.add(player)

        count += 1

        # Commit in batches of 100
        if count % 100 == 0:
            await db.flush()

    await db.commit()
    return count


async def fetch_weekly_stats(year: int, week: int) -> Dict[str, Any]:
    """Fetch weekly stats for all players from Sleeper."""
    async with httpx.AsyncClient() as client:
        # The season_type ("regular") path segment is required. Without it,
        # Sleeper doesn't 404 -- it silently returns a degenerate payload of
        # rank fields only (pos_rank_ppr, rank_std, ...) with none of the
        # actual box-score stat keys (pass_yd, rush_td, rec, ...), so every
        # scoring calculation against synced weekly stats silently comes out
        # to 0. Confirmed against the live API before applying this fix.
        response = await client.get(
            f"{SLEEPER_API}/stats/nfl/regular/{year}/{week}"
        )
        response.raise_for_status()
        return response.json()


async def fetch_player_week_stats(year: int, week: int, player_id: str) -> Dict[str, Any]:
    """Fetch weekly stats for a single player by Sleeper ID."""
    all_stats = await fetch_weekly_stats(year, week)
    return all_stats.get(player_id, {})


async def fetch_player_season_stats(year: int, player_id: str) -> Dict[str, Any]:
    """Fetch full season stats for a single player."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SLEEPER_API}/stats/nfl/player/{player_id}?season_type=regular&season={year}"
        )
        response.raise_for_status()
        return response.json()


async def sync_weekly_stats(db: AsyncSession, year: int, week: int) -> int:
    """Sync weekly stats from Sleeper to local player records."""
    stats_data = await fetch_weekly_stats(year, week)
    count = 0

    for player_id, stats in stats_data.items():
        result = await db.execute(
            select(Player).where(Player.sleeper_id == player_id)
        )
        player = result.scalar_one_or_none()
        if not player:
            continue

        # A new season starting resets accumulated stats instead of piling
        # onto whatever the previous season left behind -- without this,
        # week 1 of a new year would silently add on top of last year's
        # final totals rather than starting fresh from zero.
        if player.stats_year != year:
            player.stats = {}
            player.week_stats = {}
            player.stats_year = year

        # Update week stats
        week_key = str(week)
        if not player.week_stats:
            player.week_stats = {}
        player.week_stats[week_key] = stats

        # Also update aggregated stats
        if not player.stats:
            player.stats = {}
        for key, value in stats.items():
            if key in player.stats:
                if isinstance(value, (int, float)):
                    player.stats[key] = (player.stats[key] or 0) + value
            else:
                player.stats[key] = value

        count += 1

        if count % 100 == 0:
            await db.flush()

    await db.commit()
    return count


def transform_player_position(sleeper_position: str) -> str:
    """Convert Sleeper position codes to standard format."""
    mapping = {
        "QB": "QB",
        "RB": "RB",
        "WR": "WR",
        "TE": "TE",
        "K": "K",
        "DEF": "DEF",
        "DB": "DB",
        "DL": "DL",
        "LB": "LB",
    }
    return mapping.get(sleeper_position, "UNKNOWN")


def sleeper_avatar_url(sleeper_id: Optional[str]) -> Optional[str]:
    """Build a player's Sleeper CDN headshot URL. Single source of truth —
    every endpoint that serializes a player should use this instead of
    building the URL inline."""
    if not sleeper_id:
        return None
    return f"https://sleepercdn.com/content/nfl/players/{sleeper_id}.jpg"


# Compact, position-appropriate stat keys to surface as a "headline" summary
# rather than dumping the full raw stat blob everywhere.
HEADLINE_STAT_KEYS: Dict[str, list] = {
    "QB": ["pass_yd", "pass_td", "pass_int"],
    "RB": ["rush_yd", "rush_td", "rec"],
    "WR": ["rec", "rec_yd", "rec_td"],
    "TE": ["rec", "rec_yd", "rec_td"],
    "K": ["fgm", "xpm"],
    "DEF": ["idp_tkl", "idp_sack"],
    "DL": ["idp_tkl", "idp_sack"],
    "LB": ["idp_tkl", "idp_sack"],
    "DB": ["idp_tkl", "idp_int"],
}


def headline_stats(position: str, stats: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Pick a compact set of stat lines for a player based on position.
    Returns {} if there's no stats data yet (nothing synced, or unknown position)."""
    if not stats:
        return {}
    keys = HEADLINE_STAT_KEYS.get(position, [])
    return {k: stats[k] for k in keys if k in stats and stats[k] is not None}


async def sync_season_stats(db: AsyncSession, season: str) -> int:
    """Fetch full-season aggregate stats for every player and store them on
    Player.stats -- the CURRENT season's live totals (see stats_year /
    effective_season_stats). For archiving a completed prior season as the
    season_points fallback reference instead, use
    archive_last_season_stats, which writes to a separate field so the two
    don't collide."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SLEEPER_API}/stats/nfl/regular/{season}", timeout=60
        )
        response.raise_for_status()
        stats_data = response.json()

    count = 0
    for sleeper_id, stats in stats_data.items():
        result = await db.execute(
            select(Player).where(Player.sleeper_id == sleeper_id)
        )
        player = result.scalar_one_or_none()
        if not player:
            continue

        player.stats = stats
        player.stats_year = int(season)
        count += 1

        if count % 500 == 0:
            await db.flush()

    await db.commit()
    return count


async def archive_last_season_stats(db: AsyncSession, season: int) -> int:
    """Snapshot a fully-completed season's aggregate stats into
    Player.last_season_stats/last_season_year -- a static reference kept
    separate from Player.stats (which tracks the CURRENT, in-progress
    season and resets at each season boundary, see sync_weekly_stats). This
    is what season_points falls back to before the new season has any real
    synced data of its own."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SLEEPER_API}/stats/nfl/regular/{season}", timeout=60
        )
        response.raise_for_status()
        stats_data = response.json()

    count = 0
    for sleeper_id, stats in stats_data.items():
        result = await db.execute(
            select(Player).where(Player.sleeper_id == sleeper_id)
        )
        player = result.scalar_one_or_none()
        if not player:
            continue

        player.last_season_stats = stats
        player.last_season_year = season
        count += 1

        if count % 500 == 0:
            await db.flush()

    await db.commit()
    return count
