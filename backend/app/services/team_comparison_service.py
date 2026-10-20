"""
Team Comparison (full-season trend) -- AI Analysis extension,
2026-09-22. Compares two teams IN THE SAME LEAGUE across their whole
season so far: weekly scoring trend, consistency, and position-group
strength -- deliberately NOT a single-week matchup preview (that
context already exists via analyze_lineup's opponent_roster/matchups).
"""
from statistics import mean, pstdev
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team
from app.models.player import Player
from app.models.weekly_score import WeeklyScore
from app.services.scoring_engine import calculate_player_score

# Broad position groups for the "where does this team's production
# come from" breakdown -- IDP positions folded into one bucket since a
# league without IDP roster slots has none of these anyway, and a
# league that does still wants "IDP" as one line, not three thin ones.
_POSITION_GROUPS: dict[str, str] = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DEF": "DEF",
    "DL": "IDP", "LB": "IDP", "DB": "IDP",
}

# Below this many scored weeks, a trend read (up/down/steady) is mostly
# noise -- reported as "insufficient data" instead of a confident-
# sounding label the AI prompt might otherwise take too literally.
MIN_WEEKS_FOR_TREND = 3


async def _weekly_totals(team_id: str, db: AsyncSession) -> list[dict[str, Any]]:
    """This team's real WeeklyScore rows so far this season, oldest
    first -- the actual scored totals under the league's own scoring
    config (not a recompute), same source of truth the Standings/
    Schedule pages already use."""
    result = await db.execute(
        select(WeeklyScore).where(WeeklyScore.team_id == team_id).order_by(WeeklyScore.year, WeeklyScore.week)
    )
    rows = result.scalars().all()
    if not rows:
        return []
    # Only the latest season this team has scores in (no carry-over rows
    # from a prior year inflating games_played).
    season = max(w.year for w in rows)
    return [{"week": w.week, "points": round(w.total_score, 2)} for w in rows if w.year == season]


async def _position_group_points(team: Team, db: AsyncSession, scoring: dict) -> dict[str, float]:
    """Season-aggregate points (Player.stats -- the running season
    total kept current by sleeper_sync.sync_weekly_stats) for this
    team's CURRENT roster, grouped into broad position buckets. Reflects
    who's on the team NOW, not who scored each historical point -- a
    roster moved mid-season won't retroactively re-attribute points,
    same "current roster" limitation Standings' own team breakdowns
    already have."""
    if not team.roster:
        return {}
    result = await db.execute(select(Player).where(Player.id.in_(team.roster)))
    totals: dict[str, float] = {}
    for p in result.scalars().all():
        group = _POSITION_GROUPS.get(p.position, p.position)
        points = calculate_player_score(p.stats or {}, scoring, p.position)
        totals[group] = round(totals.get(group, 0.0) + points, 2)
    return totals


def _trend_label(points: list[float]) -> str:
    if len(points) < MIN_WEEKS_FOR_TREND:
        return "insufficient data"
    # Compares the average of the first half of scored weeks against
    # the second half -- simple and explainable (the LLM gets the raw
    # weekly_points list too, so it can reason more finely if useful),
    # rather than a fitted regression slope that's harder to sanity-check.
    midpoint = len(points) // 2
    early, recent = mean(points[:midpoint]), mean(points[midpoint:])
    if recent > early * 1.05:
        return "up"
    if recent < early * 0.95:
        return "down"
    return "steady"


async def build_team_trend(team: Team, db: AsyncSession, scoring: dict) -> dict[str, Any]:
    """Everything the AI comparison needs for one team's season so
    far: weekly points, games played, average, week-to-week consistency
    (population stdev -- lower means steadier), a simple trend label,
    and current-roster position-group strength."""
    weekly = await _weekly_totals(team.id, db)
    points = [w["points"] for w in weekly]
    return {
        "team_name": team.name,
        "weekly_points": weekly,
        "games_played": len(points),
        # A league created mid-season only has scores from the week it
        # started (QA 2026-10-19: "Week 6" yet "only one game played" read
        # as a contradiction). Lets the analysis say *why* the sample is small.
        "first_scored_week": weekly[0]["week"] if weekly else None,
        "latest_scored_week": weekly[-1]["week"] if weekly else None,
        "average_points": round(mean(points), 2) if points else 0.0,
        "consistency_stdev": round(pstdev(points), 2) if len(points) > 1 else 0.0,
        "trend": _trend_label(points),
        "position_group_points": await _position_group_points(team, db, scoring),
    }
