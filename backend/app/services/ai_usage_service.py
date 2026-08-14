"""
Per-league daily cap on real LLM-spend calls (AI Co-Commissioner v1).

The existing per-IP hourly rate limits (slowapi, see core/limiter.py)
bound call *volume* per client IP, but don't bound *spend* per league
and don't stop usage spread across multiple IPs. This adds a second,
independent ceiling: how many real LLM calls a single league can make
in a rolling 24 hours, tracked in the database (AIUsageEvent) rather
than in-process memory -- so it holds regardless of which IP the
request came from, and survives a redeploy (unlike slowapi's in-memory
counters).

Only wraps the endpoints that actually spend money: digest generate,
trade review analyze, message draft, chat post. The zero-LLM tools
(League Health/Scoring Insights/Schedule Insights) never call this --
they cost nothing, so there's nothing to cap.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_usage_event import AIUsageEvent

# How many real LLM calls one league can make in a rolling 24 hours.
# At gpt-5.6-luna pricing, even every call being the priciest one
# (Chat) this is well under $1/day worst case per league -- generous
# for real use, but a real ceiling against a runaway script/bug or a
# botnet spread across many IPs (which the per-IP hourly limiter alone
# doesn't stop). Named constant, tunable after seeing real usage.
DAILY_AI_LIMIT_PER_LEAGUE = 50


async def check_and_record_ai_usage(league_id: str, endpoint: str, db: AsyncSession) -> None:
    """Raises 429 if this league has hit its daily cap; otherwise
    records this call and lets the caller proceed. Call this AFTER
    require_commissioner/_require_ai_enabled (it's a cost guard, not an
    authorization check) and BEFORE the actual LLM call, so a call that
    would be rejected never spends anything. Fire-and-forget within the
    caller's own transaction, like notification_service's
    create_notification -- the caller commits it alongside whatever
    else the request does."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    count = await db.scalar(
        select(func.count(AIUsageEvent.id)).where(
            AIUsageEvent.league_id == league_id,
            AIUsageEvent.created_at >= cutoff,
        )
    )
    if count is not None and count >= DAILY_AI_LIMIT_PER_LEAGUE:
        raise HTTPException(
            status_code=429,
            detail=(
                f"This league has reached its daily AI usage limit "
                f"({DAILY_AI_LIMIT_PER_LEAGUE} calls per 24 hours). Try again later."
            ),
        )
    db.add(AIUsageEvent(league_id=league_id, endpoint=endpoint))
