"""
League Health Dashboard (AI Co-Commissioner v1, Phase 1).

Deliberately zero LLM calls -- every metric here is real arithmetic
over data that already exists (Lineup rows, Transaction rows,
WeeklyScore-derived standings), computed fresh on every request. This
directly serves the "feel fast" and "transparent reasoning" goals of
the spec better than an AI summary would, and costs nothing per view
(unlike the digest/trade review, which spend real LLM money and are
cached specifically because of that -- see commissioner_digest_service.py/
trade_review_service.py).

Two known, deliberate limitations, both documented in the plan and
surfaced honestly to the commissioner in the API response rather than
silently glossed over:

1. Lineup-setting rate is meaningless for Best-Ball leagues -- a
   best-ball team never produces real Lineup rows regardless of how
   engaged its owner actually is (starters come from an always-on
   optimizer, see best_ball_service.py), so this metric is `None` for
   those leagues rather than a misleading 0%.
2. Neither Transaction nor Lineup records *which* of a co-owned team's
   two owners took an action -- only the team. A co-owned team's low
   engagement can be flagged; which specific partner is inactive
   cannot be determined from existing data.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.league import League
from app.models.team import Team
from app.models.lineup import Lineup
from app.models.transaction import Transaction
from app.models.weekly_score import WeeklyScore
from app.services.best_ball_service import get_best_ball_settings
from app.services.standings_service import get_standings

# Named thresholds, not magic numbers -- easy to tune once this has
# been used against real league data.
AT_RISK_LINEUP_RATE = 0.5   # below this fraction of weeks with a set lineup...
AT_RISK_MAX_TRANSACTIONS = 0  # ...and this few transactions all season -> at-risk


async def compute_league_health(
    league: League, db: AsyncSession, standings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """standings: pass a pre-computed get_standings(league.id, db) result
    when the caller already has one in hand (chat_service.build_chat_context
    calls this + compute_strength_of_schedule + get_standings itself on
    every chat turn -- without this, that's 3 full standings recomputes
    for one message). None (default) computes it fresh, unchanged for
    every other caller (this endpoint's own direct GET, message_service)."""
    teams_result = await db.execute(select(Team).where(Team.league_id == league.id))
    teams = teams_result.scalars().all()

    if not teams:
        return {
            "teams": [], "parity_spread": 0.0, "at_risk_count": 0,
            "total_teams": 0, "is_best_ball": get_best_ball_settings(league)["enabled"],
        }

    is_best_ball = get_best_ball_settings(league)["enabled"]
    team_ids = [t.id for t in teams]

    # "Weeks elapsed so far" -- distinct (week, year) with any WeeklyScore
    # for this league. Floor of 1 avoids a /0 in the pre-season case
    # (no weeks scored yet), where every rate is trivially 0 anyway.
    weeks_result = await db.execute(
        select(WeeklyScore.week, WeeklyScore.year)
        .where(WeeklyScore.league_id == league.id)
        .distinct()
    )
    weeks_elapsed = max(len(weeks_result.all()), 1)

    lineup_counts: dict[str, int] = {}
    if not is_best_ball:
        lu_result = await db.execute(
            select(Lineup.team_id, func.count(Lineup.id))
            .where(Lineup.team_id.in_(team_ids))
            .group_by(Lineup.team_id)
        )
        lineup_counts = dict(lu_result.all())

    tx_result = await db.execute(
        select(Transaction.team_id, func.count(Transaction.id))
        .where(Transaction.league_id == league.id)
        .group_by(Transaction.team_id)
    )
    transaction_counts = dict(tx_result.all())

    if standings is None:
        standings = await get_standings(league.id, db)
    points = [s["points_for"] for s in standings] or [0.0]
    avg_points = sum(points) / len(points) if points else 0.0
    parity_spread = (
        round((max(points) - min(points)) / avg_points, 2)
        if len(points) > 1 and avg_points > 0
        else 0.0
    )

    team_health = []
    for t in teams:
        tx_count = transaction_counts.get(t.id, 0)
        if is_best_ball:
            lineup_rate = None
            at_risk = False
            reason = "Best-Ball league -- lineups are set automatically, so this team's engagement can't be measured this way."
        else:
            lineup_rate = round(lineup_counts.get(t.id, 0) / weeks_elapsed, 2)
            at_risk = lineup_rate < AT_RISK_LINEUP_RATE and tx_count <= AT_RISK_MAX_TRANSACTIONS
            if at_risk:
                reason = (
                    f"Set a lineup in only {round(lineup_rate * 100)}% of weeks so far "
                    f"and has made {tx_count} transaction(s) all season."
                )
            else:
                reason = f"Set a lineup in {round(lineup_rate * 100)}% of weeks so far, {tx_count} transaction(s) all season."

        team_health.append({
            "team_id": t.id,
            "team_name": t.name,
            "is_co_owned": t.co_owner_id is not None,
            "lineup_rate": lineup_rate,
            "transaction_count": tx_count,
            "at_risk": at_risk,
            "reason": reason,
        })

    return {
        "teams": team_health,
        "parity_spread": parity_spread,
        "at_risk_count": sum(1 for th in team_health if th["at_risk"]),
        "total_teams": len(teams),
        "is_best_ball": is_best_ball,
    }
