"""
Per-user persisted history for the personal AI Analysis tools (Lineup/
Trade/Bet, POST /ai/lineup|trade|bet). These were pure one-shot
request/response calls with nothing saved anywhere -- AIUsageEvent logs
that a call happened (for spend metering), but never the actual
question/answer, so a result was gone the moment you left the page or
refreshed. This is the content-storage counterpart to
ai_usage_service.record_ai_usage: same "fire-and-forget within the
caller's own transaction" convention as that and
notification_service.create_notification (the caller's own db.commit()
covers the add()).

Deliberately NOT threaded into a new LLM call the way chat_service's
history is -- these tools stay one-shot Q&A, no conversational context.
This only makes past answers retrievable; it doesn't change what the AI
sees on the next call.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_analysis_history import AIAnalysisHistory

# How many past results the history list returns -- a plain recency
# list, not a paged archive. Starting point, easy to tune once this has
# real usage behind it, same spirit as chat_service.MAX_HISTORY_MESSAGES.
HISTORY_LIMIT = 20


async def record_analysis(
    db: AsyncSession,
    *,
    user_id: str,
    analysis_type: str,
    summary: str,
    result: str,
    league_id: str | None = None,
) -> None:
    """Persists one past result. Not committed here -- every call site
    already does its own db.commit() right after recording AI usage;
    this rides along in that same transaction."""
    db.add(AIAnalysisHistory(
        user_id=user_id,
        league_id=league_id,
        analysis_type=analysis_type,
        summary=summary,
        result=result,
    ))


async def get_analysis_history(
    db: AsyncSession,
    *,
    user_id: str,
    analysis_type: str,
    league_id: str | None = None,
    limit: int = HISTORY_LIMIT,
) -> list[AIAnalysisHistory]:
    """Newest first -- a plain recency list for display, unlike
    chat_service.get_chat_history (oldest-first, since that result
    feeds back into an LLM prompt). league_id, when given, narrows to
    that league only (used by the Lineup/Trade tabs, which are always
    scoped to a chosen league); omitted for Bet, which has none."""
    query = select(AIAnalysisHistory).where(
        AIAnalysisHistory.user_id == user_id,
        AIAnalysisHistory.analysis_type == analysis_type,
    )
    if league_id is not None:
        query = query.where(AIAnalysisHistory.league_id == league_id)
    query = query.order_by(AIAnalysisHistory.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
