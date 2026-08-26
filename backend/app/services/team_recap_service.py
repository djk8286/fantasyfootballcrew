"""
Per-Team Weekly Performance Recap -- Dashboard AI Summaries initiative.

One LLM call produces a short blurb for EVERY team in a league at once
(not one call per team) -- N times cheaper, and mirrors how
CommissionerDigest's own POWER RANKINGS section already covers every
team in a single pass. Rendered on the league's own dashboard page
(/leagues/[id]), not buried in the commissioner-only tab -- every
manager should see their team's recap without needing commissioner
access. Mirrors commissioner_digest_service.py's shape exactly,
scoped to (league_id, week, year).
"""
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.league import League
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.models.player import Player
from app.models.team_weekly_recap import TeamWeeklyRecap
from app.services.standings_service import _effective_matchups
from app.services.ai_service import AIService


def _get_ai_service() -> AIService:
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def build_team_recap_context(league: League, week: int, year: int, db: AsyncSession) -> list[dict[str, Any]]:
    """One entry per team: this week's score, W/L/T/bye result, their
    opponent, and their single top-scoring starter (name resolved via
    Player -- lineup_data's breakdown is keyed by player_id only)."""
    teams_result = await db.execute(select(Team).where(Team.league_id == league.id))
    teams = teams_result.scalars().all()
    team_by_id = {t.id: t for t in teams}
    if not teams:
        return []

    scores_result = await db.execute(
        select(WeeklyScore).where(
            WeeklyScore.league_id == league.id, WeeklyScore.week == week, WeeklyScore.year == year,
        )
    )
    score_by_team = {s.team_id: s for s in scores_result.scalars().all()}
    if not score_by_team:
        return []

    # Batch-resolve every top-scorer player_id across all teams in one
    # query, same "don't query per-team in a loop" discipline as
    # standings_service.calculate_week.
    top_scorer_ids: dict[str, str] = {}
    for team_id, score in score_by_team.items():
        breakdown = (score.lineup_data or {}).get("breakdown") or {}
        if breakdown:
            best_pid = max(breakdown, key=lambda pid: breakdown[pid].get("score", 0))
            top_scorer_ids[team_id] = best_pid
    players_result = await db.execute(select(Player).where(Player.id.in_(set(top_scorer_ids.values()))))
    players_by_id = {p.id: p for p in players_result.scalars().all()}

    matchups = _effective_matchups(league, teams, week)
    opponent_of: dict[str, str] = {}
    for a, b in matchups:
        opponent_of[a] = b
        opponent_of[b] = a

    context = []
    for team in teams:
        score = score_by_team.get(team.id)
        if not score:
            continue
        opp_id = opponent_of.get(team.id)
        opponent = team_by_id.get(opp_id) if opp_id else None
        opp_score = score_by_team.get(opp_id) if opp_id else None

        result = "bye"
        if opponent and opp_score:
            if score.total_score > opp_score.total_score:
                result = "win"
            elif score.total_score < opp_score.total_score:
                result = "loss"
            else:
                result = "tie"

        top_pid = top_scorer_ids.get(team.id)
        top_player = players_by_id.get(top_pid) if top_pid else None
        breakdown = (score.lineup_data or {}).get("breakdown") or {}
        top_score = breakdown.get(top_pid, {}).get("score", 0) if top_pid else 0

        context.append({
            "team_name": team.name,
            "total_score": round(score.total_score, 2),
            "result": result,
            "opponent_name": opponent.name if opponent else None,
            "opponent_score": round(opp_score.total_score, 2) if opp_score else None,
            "top_performer": f"{top_player.first_name} {top_player.last_name}" if top_player else None,
            "top_performer_points": round(top_score, 2) if top_player else None,
        })
    return context


async def get_recap(league_id: str, week: int, year: int, db: AsyncSession) -> TeamWeeklyRecap | None:
    result = await db.execute(
        select(TeamWeeklyRecap).where(
            TeamWeeklyRecap.league_id == league_id, TeamWeeklyRecap.week == week, TeamWeeklyRecap.year == year,
        )
    )
    return result.scalar_one_or_none()


async def get_latest_recap(league_id: str, db: AsyncSession) -> TeamWeeklyRecap | None:
    """Most recently generated recap for this league -- lets the
    league dashboard display this ambiently (no week-picker UI) the
    same way the NFL-wide panels do, rather than requiring the caller
    to already know which week to ask for."""
    result = await db.execute(
        select(TeamWeeklyRecap).where(TeamWeeklyRecap.league_id == league_id).order_by(
            TeamWeeklyRecap.year.desc(), TeamWeeklyRecap.week.desc(),
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def generate_and_save_recap(
    league: League, week: int, year: int, generated_by: str | None, db: AsyncSession,
) -> TeamWeeklyRecap | None:
    """Returns None (does not create a row) if there's no scored data
    for this week yet -- same "nothing to summarize" no-op every other
    generator in this file follows, rather than persisting an empty/
    placeholder recap."""
    context = await build_team_recap_context(league, week, year, db)
    if not context:
        return None

    service = _get_ai_service()
    content = await service.generate_team_recaps(league_name=league.name, week=week, year=year, teams=context)

    existing = await get_recap(league.id, week, year, db)
    if existing:
        existing.content = content
        existing.generated_by = generated_by
        recap = existing
    else:
        recap = TeamWeeklyRecap(league_id=league.id, week=week, year=year, content=content, generated_by=generated_by)
        db.add(recap)

    await db.commit()
    await db.refresh(recap)
    return recap
