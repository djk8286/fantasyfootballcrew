"""
Top NFL Performers This Week -- Dashboard AI Summaries initiative.

Cross-league (not scoped to any one league's custom scoring rules,
unlike standings_service.calculate_week) -- ranks every synced player
by DEFAULT_SCORING for a given week, purely as a standard/representative
fantasy-points measure for "who had a big week," not tied to what any
specific league actually pays out. Mirrors commissioner_digest_service.py's
own shape (context-builder + get-cached + generate-and-save), scoped to
(week, year) instead of (league_id, week, year).
"""
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.models.player import Player
from app.models.weekly_top_players_summary import WeeklyTopPlayersSummary
from app.services.scoring_engine import calculate_player_score, DEFAULT_SCORING
from app.services.ai_service import AIService

TOP_N = 12


def _get_ai_service() -> AIService:
    """Same factory ai.py/commissioner_digest_service.py use -- duplicated
    (it's 3 lines) rather than shared."""
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def compute_top_performers(week: int, year: int, db: AsyncSession) -> list[dict[str, Any]]:
    """Every player with a real stat line for this week, scored under
    DEFAULT_SCORING, highest first. A player who didn't play (no
    week_stats entry for this week at all) is excluded outright rather
    than scored as 0 -- a real 0-point game and "didn't play" aren't
    the same thing, and only the former belongs on a "top performers"
    list's low end (which TOP_N never reaches anyway in practice)."""
    week_key = str(week)
    result = await db.execute(select(Player))
    scored = []
    for p in result.scalars().all():
        stats = (p.week_stats or {}).get(week_key)
        if not stats:
            continue
        points = calculate_player_score(stats, DEFAULT_SCORING, p.position)
        scored.append({
            "name": f"{p.first_name} {p.last_name}",
            "position": p.position,
            "team": p.team or "FA",
            "points": round(points, 2),
        })
    scored.sort(key=lambda x: x["points"], reverse=True)
    return scored[:TOP_N]


async def get_summary(week: int, year: int, db: AsyncSession) -> WeeklyTopPlayersSummary | None:
    result = await db.execute(
        select(WeeklyTopPlayersSummary).where(
            WeeklyTopPlayersSummary.week == week, WeeklyTopPlayersSummary.year == year,
        )
    )
    return result.scalar_one_or_none()


async def generate_and_save_summary(week: int, year: int, db: AsyncSession) -> WeeklyTopPlayersSummary:
    top_players = await compute_top_performers(week, year, db)
    service = _get_ai_service()
    content = await service.generate_top_players_summary(week=week, year=year, top_players=top_players)

    existing = await get_summary(week, year, db)
    if existing:
        existing.content = content
        existing.top_players = top_players
        summary = existing
    else:
        summary = WeeklyTopPlayersSummary(week=week, year=year, content=content, top_players=top_players)
        db.add(summary)

    await db.commit()
    await db.refresh(summary)
    return summary
