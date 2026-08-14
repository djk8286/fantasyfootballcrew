"""
Rule & Scoring Balance Insights (AI Co-Commissioner v1, Phase 2).

Zero-LLM, computed-data pattern -- identical rationale to
league_health_service.py: real arithmetic over existing rows, plain-
English explanation strings generated in Python, no persistence
(recomputed fresh every request), no LLM cost to protect with a rate
limit. Surfaces three independent observation groups, each presented
as a suggestion with supporting data, never an instruction -- the
commissioner decides whether any of it is worth acting on.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.league import League
from app.models.team import Team
from app.models.coach import Coach
from app.models.weekly_score import WeeklyScore
from app.services.scoring_engine import calculate_player_score_by_category

# "Several weeks of data" per spec -- avoid noisy/misleading
# conclusions off 1-2 weeks of small-sample randomness.
MIN_WEEKS_FOR_INSIGHTS = 3

# A category's coefficient of variation (stdev / mean, across every
# team-week's points from that category) above this is flagged as
# "high variance" -- i.e. it swings score outcomes a lot more than a
# typical category does. Starting point, easy to tune once this has
# been run against real league data.
HIGH_VARIANCE_CV = 0.9

# Average bonus points per team-week, as a share of average total
# points per team-week, above which a configured coach bonus_type is
# flagged as possibly over-powered.
OVERPOWERED_BONUS_SHARE = 0.15
# Average bonus points per team-week below which a configured
# bonus_type is flagged as barely moving the needle.
UNDERPOWERED_BONUS_FLOOR = 0.5

# Ratio between a position's highest and lowest average per-player-
# per-week score at which the gap is worth flagging as a positional
# imbalance.
POSITIONAL_GAP_RATIO = 2.0


async def compute_scoring_insights(league: League, db: AsyncSession) -> dict[str, Any]:
    weeks_result = await db.execute(
        select(WeeklyScore.week, WeeklyScore.year)
        .where(WeeklyScore.league_id == league.id)
        .distinct()
    )
    weeks = weeks_result.all()
    if len(weeks) < MIN_WEEKS_FOR_INSIGHTS:
        return {
            "available": False,
            "weeks_available": len(weeks),
            "weeks_required": MIN_WEEKS_FOR_INSIGHTS,
        }

    scores_result = await db.execute(
        select(WeeklyScore).where(WeeklyScore.league_id == league.id)
    )
    weekly_scores = scores_result.scalars().all()

    return {
        "available": True,
        "weeks_available": len(weeks),
        "category_variance": _compute_category_variance(weekly_scores, league.scoring_config or {}),
        "coach_bonus_impact": await _compute_coach_bonus_impact(league, weekly_scores, db),
        "positional_balance": _compute_positional_balance(weekly_scores),
    }


def _compute_category_variance(weekly_scores: list[WeeklyScore], scoring_config: dict) -> list[dict[str, Any]]:
    """Re-derives each player-week's per-category points (not stored --
    only the summed total is) against the league's actual scoring
    config, sums to a per-team-week total per category, then looks at
    how much each category's contribution swings across all
    team-weeks league-wide."""
    if not scoring_config:
        return []

    per_category_team_week_totals: dict[str, list[float]] = defaultdict(list)
    for ws in weekly_scores:
        breakdown = (ws.lineup_data or {}).get("breakdown") or {}
        team_week_by_category: dict[str, float] = defaultdict(float)
        for player_entry in breakdown.values():
            stats = player_entry.get("stats") or {}
            for category, points in calculate_player_score_by_category(stats, scoring_config).items():
                team_week_by_category[category] += points
        for category, total in team_week_by_category.items():
            per_category_team_week_totals[category].append(total)

    observations = []
    for category, totals in per_category_team_week_totals.items():
        if len(totals) < 2:
            continue
        mean = statistics.mean(totals)
        if mean == 0:
            continue
        cv = round(statistics.stdev(totals) / abs(mean), 2)
        if cv >= HIGH_VARIANCE_CV:
            observations.append({
                "category": category,
                "coefficient_of_variation": cv,
                "average_points": round(mean, 2),
                "summary": (
                    f'"{category}" scoring swings a lot week to week (avg {round(mean, 2)} pts, '
                    f"variance ratio {cv}) -- worth a look if that feels like more randomness than "
                    f"skill in your league's results."
                ),
            })

    observations.sort(key=lambda o: o["coefficient_of_variation"], reverse=True)
    return observations


async def _compute_coach_bonus_impact(league: League, weekly_scores: list[WeeklyScore], db: AsyncSession) -> list[dict[str, Any]]:
    """Only evaluates bonus_types actually configured by at least one
    active coach in the league -- a bonus_type nobody uses has nothing
    to observe about."""
    teams_result = await db.execute(select(Team.id).where(Team.league_id == league.id))
    team_ids = [row[0] for row in teams_result.all()]
    if not team_ids:
        return []

    coaches_result = await db.execute(
        select(Coach.bonus_type).where(
            Coach.team_id.in_(team_ids), Coach.is_active.is_(True), Coach.bonus_type.is_not(None)
        )
    )
    configured_bonus_types = {row[0] for row in coaches_result.all()}
    if not configured_bonus_types:
        return []

    # See standings_service._coach_bonus_sum / calculate_week -- these
    # are the two lineup_data keys a coach bonus ever lands under.
    bonus_key_by_type = {"flat_weekly": "coach_bonus", "win_bonus": "win_bonus"}

    total_scores = [ws.total_score for ws in weekly_scores]
    avg_total = statistics.mean(total_scores) if total_scores else 0.0

    observations = []
    for bonus_type in sorted(configured_bonus_types):
        key = bonus_key_by_type.get(bonus_type)
        if not key:
            continue
        bonus_values = [
            (ws.lineup_data or {}).get(key, 0.0)
            for ws in weekly_scores
            if key in (ws.lineup_data or {})
        ]
        if not bonus_values:
            continue
        avg_bonus = statistics.mean(bonus_values)
        share = round(avg_bonus / avg_total, 2) if avg_total else 0.0

        if share >= OVERPOWERED_BONUS_SHARE:
            observations.append({
                "bonus_type": bonus_type,
                "average_bonus_points": round(avg_bonus, 2),
                "share_of_average_score": share,
                "summary": (
                    f'"{bonus_type}" coach bonuses add {round(avg_bonus, 2)} pts on average when they '
                    f"apply -- about {int(share * 100)}% of an average team-week's score. May be worth "
                    f"a look if that feels disproportionate."
                ),
            })
        elif avg_bonus < UNDERPOWERED_BONUS_FLOOR:
            observations.append({
                "bonus_type": bonus_type,
                "average_bonus_points": round(avg_bonus, 2),
                "share_of_average_score": share,
                "summary": (
                    f'"{bonus_type}" coach bonuses add only {round(avg_bonus, 2)} pts on average -- '
                    f"barely moves the needle as currently configured."
                ),
            })

    return observations


def _compute_positional_balance(weekly_scores: list[WeeklyScore]) -> list[dict[str, Any]]:
    scores_by_position: dict[str, list[float]] = defaultdict(list)
    for ws in weekly_scores:
        breakdown = (ws.lineup_data or {}).get("breakdown") or {}
        for player_entry in breakdown.values():
            position = player_entry.get("position")
            score = player_entry.get("score")
            if position and score is not None:
                scores_by_position[position].append(float(score))

    averages = {
        position: round(statistics.mean(scores), 2)
        for position, scores in scores_by_position.items()
        if scores
    }
    if len(averages) < 2:
        return []

    highest_position = max(averages, key=averages.get)
    lowest_position = min(averages, key=averages.get)
    highest, lowest = averages[highest_position], averages[lowest_position]

    if lowest <= 0 or highest / lowest < POSITIONAL_GAP_RATIO:
        return []

    return [{
        "highest_position": highest_position,
        "highest_average": highest,
        "lowest_position": lowest_position,
        "lowest_average": lowest,
        "summary": (
            f"{highest_position} averages {highest} pts/week versus {lowest_position}'s {lowest} -- "
            f"a {round(highest / lowest, 1)}x gap. Worth checking if your roster slots and scoring "
            f"config reflect the value split you actually want between these positions."
        ),
    }]
