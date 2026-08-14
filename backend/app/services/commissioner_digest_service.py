"""
AI-Assisted Commissioner Tools (Phase 8).

Assembles league context (standings, recent transactions, active
feature flags) and calls AIService.generate_commissioner_digest to
produce a weekly digest -- power rankings, storylines, a waiver/trade
recap. Commissioner-triggered on demand only (binding decision,
confirmed via AskUserQuestion) -- there is no scheduler integration
here at all, unlike guillotine_service.py/best_ball_service.py, which
both plug into the scheduler's weekly-cadence hooks. A generated digest
is persisted (CommissionerDigest, one row per league/week/year,
upserted on regenerate) so revisiting the commissioner panel's digest
tab never re-spends on an LLM call just to redisplay what was already
generated.
"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.league import League, LeagueType
from app.models.transaction import Transaction, TransactionStatus
from app.models.commissioner_digest import CommissionerDigest
from app.services.ai_service import AIService
from app.services.standings_service import get_standings, get_combined_standings
from app.services.salary_cap_service import get_salary_cap_settings
from app.services.best_ball_service import get_best_ball_settings


def _get_ai_service() -> AIService:
    """Same factory ai.py's own _get_ai_service uses -- duplicated here
    (it's 3 lines) rather than shared, to avoid a cross-module import
    for something this small."""
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def build_digest_context(league: League, week: int, year: int, db: AsyncSession) -> dict[str, Any]:
    """Everything the digest prompt needs, assembled once. Dual-Squad's
    combined standings and every other feature flag default to their
    "off"/empty shape when not applicable, same {}-when-absent
    convention every other AI-context helper in ai.py already follows."""
    standings = await get_standings(league.id, db)
    combined_standings = (
        await get_combined_standings(league.id, db) if league.league_type == LeagueType.DUAL_SQUAD else []
    )

    tx_result = await db.execute(
        select(Transaction).where(
            Transaction.league_id == league.id,
            Transaction.status.in_([TransactionStatus.APPROVED, TransactionStatus.DENIED]),
        ).order_by(Transaction.processed_at.desc()).limit(25)
    )
    recent_transactions = [
        {"type": t.type.value, "status": t.status.value, "details": t.details, "team_id": t.team_id}
        for t in tx_result.scalars().all()
    ]

    features = {
        "guillotine": league.league_type == LeagueType.GUILLOTINE,
        "dual_squad": league.league_type == LeagueType.DUAL_SQUAD,
        "salary_cap": get_salary_cap_settings(league)["enabled"],
        "best_ball": get_best_ball_settings(league)["enabled"],
    }

    return {
        "league_name": league.name,
        "week": week,
        "year": year,
        "standings": standings,
        "combined_standings": combined_standings,
        "recent_transactions": recent_transactions,
        "features": features,
        "scoring_config": league.scoring_config or {},
    }


async def get_digest(league_id: str, week: int, year: int, db: AsyncSession) -> CommissionerDigest | None:
    result = await db.execute(
        select(CommissionerDigest).where(
            CommissionerDigest.league_id == league_id,
            CommissionerDigest.week == week,
            CommissionerDigest.year == year,
        )
    )
    return result.scalar_one_or_none()


async def generate_and_save_digest(
    league: League, week: int, year: int, generated_by: str, db: AsyncSession,
    tone: str = "professional", length: str = "full",
) -> CommissionerDigest:
    """Calls the LLM (real spend, if a key is configured -- this is
    exactly why it's commissioner-triggered only, never on a timer) and
    upserts the result. A regenerate for the same (league, week, year)
    overwrites the existing row's content/generated_by/tone/length in
    place -- CommissionerDigest's own unique constraint would otherwise
    reject a second insert outright. tone/length (AI Co-Commissioner v1)
    are per-generation params, not a persisted league default -- see
    ai_service.py's TONE_INSTRUCTIONS/LENGTH_INSTRUCTIONS."""
    context = await build_digest_context(league, week, year, db)
    service = _get_ai_service()
    content = await service.generate_commissioner_digest(tone=tone, length=length, **context)

    existing = await get_digest(league.id, week, year, db)
    if existing:
        existing.content = content
        existing.generated_by = generated_by
        existing.tone = tone
        existing.length = length
        digest = existing
    else:
        digest = CommissionerDigest(
            league_id=league.id, week=week, year=year, content=content, generated_by=generated_by,
            tone=tone, length=length,
        )
        db.add(digest)

    await db.commit()
    await db.refresh(digest)
    return digest
