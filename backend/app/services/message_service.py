"""
Communication Helpers (AI Co-Commissioner v1, Phase 2).

Commissioner drafts a common message (trade deadline reminder,
playoff explanation, inactivity warning, general announcement) in a
chosen tone via AIService.generate_commissioner_message, reviews/edits
it, then sends it -- delivered via the existing per-user Notification
system's new league-wide broadcast helper (notification_service.
notify_league_teams), not a new delivery mechanism. There's no league
feed/message board anywhere in this app (a deliberate scope decision
made when the AI Co-Commissioner work started) -- every team owner's
existing notification bell is the "send" destination.

Two-step, matching the spec's explicit generate -> edit -> send flow:
draft_message never sends anything; send_message never calls the LLM
(it sends whatever content the caller passes, which may be the
commissioner's edited version of the draft, not necessarily the raw
AI output).
"""
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.league import League
from app.models.notification import NotificationType
from app.services.ai_service import AIService
from app.services.playoff_service import get_playoff_settings
from app.services.league_health_service import compute_league_health
from app.services.notification_service import notify_league_teams

MESSAGE_TYPES: dict[str, str] = {
    "trade_deadline": "Trade deadline reminder",
    "playoff_explanation": "Playoff format explanation",
    "inactivity_warning": "Inactivity warning",
    "general": "General announcement",
}


def _get_ai_service() -> AIService:
    """Same factory ai.py/commissioner_digest_service.py/
    trade_review_service.py all use -- duplicated (it's 3 lines)
    rather than shared."""
    if settings.OPENAI_API_KEY:
        return AIService(api_key=settings.OPENAI_API_KEY, provider="openai")
    if settings.ANTHROPIC_API_KEY:
        return AIService(api_key=settings.ANTHROPIC_API_KEY, provider="anthropic")
    return AIService(api_key=None)


async def build_message_context(league: League, message_type: str, db: AsyncSession) -> dict[str, Any]:
    """Per-message-type context, grounding the draft in real league
    data rather than a generic template -- the spec's "only use data
    the commissioner already has access to" requirement."""
    if message_type == "playoff_explanation":
        return {"playoff_settings": get_playoff_settings(league)}

    if message_type == "inactivity_warning":
        health = await compute_league_health(league, db)
        at_risk_teams = [t["team_name"] for t in health["teams"] if t["at_risk"]]
        return {"at_risk_teams": at_risk_teams}

    # trade_deadline / general: no extra grounding data beyond the
    # league name (already always passed) -- trade_deadline has no
    # deadline-date setting anywhere in this app to pull from, and
    # general is whatever custom_context the commissioner typed in.
    return {}


async def draft_message(
    league: League,
    message_type: str,
    tone: str,
    custom_context: Optional[str],
    db: AsyncSession,
) -> str:
    context = await build_message_context(league, message_type, db)
    if custom_context:
        context = {**context, "commissioner_notes": custom_context}

    service = _get_ai_service()
    return await service.generate_commissioner_message(
        league_name=league.name,
        message_type=message_type,
        tone=tone,
        context=context,
    )


async def send_message(league: League, content: str, db: AsyncSession) -> int:
    """Sends whatever content the caller passes (the commissioner's
    possibly-edited draft, not necessarily the raw AI output) to every
    team owner/co-owner via the existing Notification system. Returns
    the recipient count. Never calls the LLM."""
    recipients = await notify_league_teams(
        db, league.id, NotificationType.COMMISSIONER_MESSAGE, content,
    )
    await db.commit()
    return recipients
