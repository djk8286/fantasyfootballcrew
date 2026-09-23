"""
Player Comparison (season stats + start/sit verdict) -- AI Analysis
extension, 2026-09-22. Compares two players' season production under a
SPECIFIC league's own scoring, plus a this-week projection if one's
synced, for a direct start/sit call -- deliberately a different framing
from trade-value ("who's more valuable long-term"), which stays out of
scope here per what was actually asked for.
"""
from typing import Any

from app.models.player import Player
from app.services.scoring_engine import calculate_player_score


def build_player_profile(player: Player, scoring: dict) -> dict[str, Any]:
    """Everything the AI comparison needs for one player: season
    fantasy points under the LEAGUE's own scoring (not
    top_performers_service's DEFAULT_SCORING -- this is a specific
    league's start/sit call, so it has to use that league's real
    rules), a per-week point breakdown for a boom/bust read, and this
    player's current-week projection if Sleeper has synced one (see
    nfl_projections_service.py)."""
    weekly_points = {
        week_key: round(calculate_player_score(stats, scoring, player.position), 2)
        for week_key, stats in (player.week_stats or {}).items()
    }
    return {
        "name": f"{player.first_name} {player.last_name}",
        "position": player.position,
        "team": player.team or "Free Agent",
        "injury_status": player.injury_status or "none reported",
        "season_points": round(calculate_player_score(player.stats or {}, scoring, player.position), 2),
        "games_played": len(weekly_points),
        "weekly_points": weekly_points,
        "projected_points_this_week": (
            round(calculate_player_score(player.projected_stats, scoring, player.position), 2)
            if player.projected_stats else None
        ),
    }
