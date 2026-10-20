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
from sqlalchemy import delete, select
from app.models.player import Player
from app.models.player_projection import PlayerProjection
from app.services.sleeper_sync import SLEEPER_API
from app.services.scoring_engine import calculate_player_score

# Fields Sleeper includes on every entry regardless of whether it has a
# real projection -- an entry with ONLY these is a "no real projection"
# placeholder (confirmed directly: ~90% of the real response is exactly
# this), not an actual per-stat/point projection worth storing.
_PLACEHOLDER_ONLY_KEYS = {"adp_dd_ppr", "pos_adp_dd_ppr"}


async def fetch_week_projections(year: int, week: int, season_type: str = "regular") -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.get(f"{SLEEPER_API}/projections/nfl/{season_type}/{year}/{week}")
        response.raise_for_status()
        return response.json()


def _meaningful(proj_data: dict) -> dict:
    return {
        sleeper_id: stats for sleeper_id, stats in proj_data.items()
        if isinstance(stats, dict) and any(k not in _PLACEHOLDER_ONLY_KEYS for k in stats)
    }


async def sync_week_projections(
    db: AsyncSession, year: int, week: int, season_type: str = "regular", update_players: bool = True,
) -> int:
    """Store Sleeper's projections for one week. Returns how many players
    got a real projection.

    Regular-season weeks go into player_projections, replacing that week's
    rows, so a player who lost his projection (bye, ruled out) loses the
    row too. update_players also refreshes Player.projected_stats, the
    single current-week snapshot the players list reads. Anyone not
    projected this pass is cleared there. Before this, a player kept last
    week's number into his bye week."""
    meaningful = _meaningful(await fetch_week_projections(year, week, season_type))

    players_by_sleeper_id = {}
    if meaningful:
        result = await db.execute(select(Player).where(Player.sleeper_id.in_(meaningful.keys())))
        players_by_sleeper_id = {p.sleeper_id: p for p in result.scalars().all()}
    matched = {p.id: meaningful[sid] for sid, p in players_by_sleeper_id.items()}

    if season_type == "regular":
        await db.execute(delete(PlayerProjection).where(
            PlayerProjection.year == year, PlayerProjection.week == week,
        ))
        db.add_all(PlayerProjection(player_id=pid, year=year, week=week, stats=stats) for pid, stats in matched.items())

    if update_players:
        for player in players_by_sleeper_id.values():
            player.projected_stats = matched[player.id]
            player.projected_week = week
            player.projected_year = year
        stale = await db.execute(select(Player).where(Player.projected_stats.isnot(None)))
        for player in stale.scalars().all():
            if player.id not in matched:
                player.projected_stats = None
                player.projected_week = None
                player.projected_year = None

    await db.commit()
    return len(matched)


async def load_projections(db: AsyncSession, player_ids: list[str], year: int, week: int) -> dict[str, dict]:
    """player_id -> projected stat line for that week. Missing = no projection."""
    if not player_ids:
        return {}
    rows = await db.execute(select(PlayerProjection.player_id, PlayerProjection.stats).where(
        PlayerProjection.player_id.in_(player_ids), PlayerProjection.year == year, PlayerProjection.week == week,
    ))
    return {pid: stats for pid, stats in rows.all()}


def projected_points(stats: dict | None, scoring_config: dict, position: str | None) -> float | None:
    """A projected stat line scored with one league's rules."""
    return None if stats is None else round(calculate_player_score(stats, scoring_config, position), 2)
