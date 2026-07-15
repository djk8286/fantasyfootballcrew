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
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.player import Player


SLEEPER_API = "https://api.sleeper.app/v1"


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
        # Skip non-NFL players or incomplete data
        if not data.get("first_name") or not data.get("last_name"):
            continue

        # Check if player already exists
        result = await db.execute(
            select(Player).where(Player.sleeper_id == sleeper_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing player
            existing.team = data.get("team") or existing.team
            existing.injury_status = data.get("injury_status") or existing.injury_status
            existing.bye_week = data.get("bye_week") or existing.bye_week
            if data.get("fantasy_positions"):
                existing.fantasy_positions = data["fantasy_positions"]
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
        response = await client.get(
            f"{SLEEPER_API}/stats/nfl/{year}/{week}"
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
