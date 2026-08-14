"""
AI Co-Commissioner Chat (AI Co-Commissioner v1, deferred item 7).

A single ongoing conversation per league (not multiple named threads
-- the simplest shape that satisfies "chat with the commissioner",
matching how deliberately lean every other feature in this initiative
stayed). Every turn rebuilds a fresh league-data snapshot from the
exact same compute functions already powering the other commissioner
tabs (League Health, Scoring Insights, Schedule Insights, standings,
recent transactions) -- a static context snapshot per message, not a
tool-calling/agentic architecture (confirmed via AskUserQuestion when
this was planned). Known limitation, stated in the system prompt
itself: only covers what's in the snapshot, so a question about very
old history may not be answered accurately.
"""
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.league import League
from app.models.transaction import Transaction, TransactionStatus
from app.models.chat_message import ChatMessage
from app.services.ai_service import AIService
from app.services.standings_service import get_standings
from app.services.league_health_service import compute_league_health
from app.services.insights_service import compute_scoring_insights
from app.services.schedule_insights_service import compute_strength_of_schedule

# How many past turns get fed back to the LLM on every call -- keeps
# cost/context bounded as a conversation grows. Starting point, easy
# to tune once this has been used against a real long-running chat.
MAX_HISTORY_MESSAGES = 20


def _get_ai_service() -> AIService:
    """Same factory ai.py/commissioner_digest_service.py/
    trade_review_service.py/message_service.py all use -- duplicated
    (it's 3 lines) rather than shared."""
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def build_chat_context(league: League, db: AsyncSession) -> dict[str, Any]:
    """Everything the chat needs to ground its answers, assembled
    fresh on every turn -- pure reuse of the exact same functions
    already powering the League Health/Scoring Insights/Schedule
    Insights tabs, plus the same recent-transactions query
    commissioner_digest_service.build_digest_context already uses."""
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

    return {
        "standings": await get_standings(league.id, db),
        "league_health": await compute_league_health(league, db),
        "scoring_insights": await compute_scoring_insights(league, db),
        "schedule_insights": await compute_strength_of_schedule(league, db),
        "recent_transactions": recent_transactions,
    }


async def get_chat_history(league_id: str, db: AsyncSession, limit: int = MAX_HISTORY_MESSAGES) -> list[ChatMessage]:
    """Newest `limit` rows, returned oldest-first (chronological) --
    both for rendering and for what gets sent back to the LLM."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.league_id == league_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def send_chat_message(league: League, user_message: str, db: AsyncSession) -> ChatMessage:
    """Persists the user's turn, calls the LLM with the real
    conversation history + a fresh context snapshot, persists the
    assistant's reply (even the no-key fallback string -- never
    silently dropped), and returns the assistant's row."""
    user_row = ChatMessage(league_id=league.id, role="user", content=user_message)
    db.add(user_row)
    await db.flush()

    history_rows = await get_chat_history(league.id, db)
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    context = await build_chat_context(league, db)
    service = _get_ai_service()
    reply_content = await service.chat(league_name=league.name, context=context, history=history)

    assistant_row = ChatMessage(league_id=league.id, role="assistant", content=reply_content)
    db.add(assistant_row)
    await db.commit()
    return assistant_row


async def clear_chat_history(league_id: str, db: AsyncSession) -> None:
    """'Start fresh' -- deletes only this league's messages."""
    await db.execute(delete(ChatMessage).where(ChatMessage.league_id == league_id))
    await db.commit()
