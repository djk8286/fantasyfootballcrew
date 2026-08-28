"""
Player weekly projections -- Player Rankings Fix initiative.

Sleeper's projections endpoint (confirmed directly against the real
API before writing this): GET /v1/projections/nfl/{season_type}/{year}/{week}
returns a dict keyed by sleeper_id -> a raw per-stat projection dict for
that ONE week (same shape as the weekly stats endpoint sleeper_sync.py
already consumes), including Sleeper's own precomputed pts_ppr/
pts_half_ppr/pts_std alongside individual stat projections (rush_yd,
rec_td, etc). There is no season-aggregate projections endpoint --
"projected points for the upcoming season" is therefore stored and
exposed as a PER-GAME projection (see Player.projected_stats), scored
through this app's own scoring_engine.calculate_player_score for
consistency with how every other stat blob (stats/last_season_stats)
is turned into points, rather than trusting Sleeper's own precomputed
totals (which wouldn't reflect a specific league's custom scoring
rules) -- never presented as a fabricated season total.
"""
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.player import Player
from app.services.sleeper_sync import SLEEPER_API

# Fields Sleeper includes on every entry regardless of whether it has a
# real projection -- an entry with ONLY these is a "no real projection"
# placeholder (confirmed directly: ~90% of the real response is exactly
# this), not an actual per-stat/point projection worth storing.
_PLACEHOLDER_ONLY_KEYS = {"adp_dd_ppr", "pos_adp_dd_ppr"}


async def fetch_week_projections(year: int, week: int, season_type: str = "regular") -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{SLEEPER_API}/projections/nfl/{season_type}/{year}/{week}")
        response.raise_for_status()
        return response.json()


async def sync_week_projections(db: AsyncSession, year: int, week: int, season_type: str = "regular") -> int:
    """Batch upsert -- one query for every candidate player instead of
    one query per projected player (unlike sleeper_sync.sync_weekly_stats's
    existing per-player-query loop, which this deliberately doesn't
    copy for new code). Returns the count of players actually updated."""
    proj_data = await fetch_week_projections(year, week, season_type)
    meaningful = {
        sleeper_id: stats for sleeper_id, stats in proj_data.items()
        if any(k not in _PLACEHOLDER_ONLY_KEYS for k in stats)
    }
    if not meaningful:
        return 0

    result = await db.execute(select(Player).where(Player.sleeper_id.in_(meaningful.keys())))
    players_by_sleeper_id = {p.sleeper_id: p for p in result.scalars().all()}

    count = 0
    for sleeper_id, stats in meaningful.items():
        player = players_by_sleeper_id.get(sleeper_id)
        if not player:
            continue
        player.projected_stats = stats
        player.projected_week = week
        player.projected_year = year
        count += 1

    await db.commit()
    return count
