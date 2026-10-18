"""
AI cost tracking + optional global daily spend cap (2026-10-17).

How a provider call gets attributed to an AIUsageEvent row:

- Request path: ai_usage_service.record_ai_usage / check_and_record_ai_usage
  create the request's AIUsageEvent (in the request's own session) and
  bind it here via a ContextVar. Every real provider call AIService makes
  afterwards in that same request adds its model/tokens/cost/error onto
  THAT row in memory; the request's own later db.commit() persists it.
  One request = one row, however many provider calls it made.
- Background path (scheduler jobs -- weekly recaps, per-team news,
  dashboard summaries): nothing is bound, so each provider call writes
  its own standalone row via a fresh session, endpoint "job:<job name>"
  (job_run_service.run_job sets the job name), or "unattributed".

Recording is best-effort everywhere: a metering failure is printed and
swallowed, never allowed to break the AI call it was measuring.
"""
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import async_session
from app.models.ai_usage_event import AIUsageEvent

DAILY_SPEND_CAP_ERROR = "daily_spend_cap"
MAX_ERROR_CHARS = 1000

_current_event: ContextVar[AIUsageEvent | None] = ContextVar("ai_usage_current_event", default=None)
_current_job: ContextVar[str | None] = ContextVar("ai_usage_current_job", default=None)


class DailySpendCapReached(Exception):
    """Raised (and caught inside AIService) instead of calling the
    provider once the rolling-24h estimated spend reaches the cap."""


def bind_usage_event(event: AIUsageEvent) -> None:
    _current_event.set(event)


def set_current_job(job_name: str | None):
    return _current_job.set(job_name)


def reset_current_job(token) -> None:
    _current_job.reset(token)


def estimate_cost(model: str, input_tokens: int, output_tokens: int, web_searches: int = 0) -> float | None:
    """USD estimate from settings.AI_MODEL_PRICING. None for an unpriced
    model (still recorded, just flagged as unpriced)."""
    price = settings.AI_MODEL_PRICING.get(model)
    if price is None:
        return None
    cost = (input_tokens * price.get("input", 0.0) + output_tokens * price.get("output", 0.0)) / 1_000_000
    return round(cost + web_searches * settings.AI_WEB_SEARCH_COST_PER_CALL, 6)


def extract_usage(data: dict[str, Any]) -> tuple[int, int, int]:
    """(input_tokens, output_tokens, web_search_calls) from a raw provider
    response. Handles OpenAI Chat Completions (prompt/completion_tokens),
    OpenAI Responses + Anthropic Messages (input/output_tokens)."""
    usage = data.get("usage") or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens")) or 0
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens")) or 0
    searches = sum(1 for item in data.get("output") or [] if isinstance(item, dict) and item.get("type") == "web_search_call")
    return int(input_tokens), int(output_tokens), searches


async def daily_spend_usd() -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    async with async_session() as db:
        total = await db.scalar(select(func.sum(AIUsageEvent.cost_usd)).where(AIUsageEvent.created_at >= cutoff))
    return float(total or 0.0)


async def check_spend_cap() -> None:
    """Raise DailySpendCapReached if a cap is configured and reached.
    A failure to evaluate the cap (DB hiccup) fails OPEN -- the cap is a
    budget guard, not a security boundary, and shouldn't take AI down."""
    cap = settings.AI_DAILY_SPEND_CAP_USD
    if cap is None:
        return
    try:
        spent = await daily_spend_usd()
    except Exception as e:
        print(f"[ai_cost] spend-cap check failed (allowing call): {e}")
        return
    if spent >= cap:
        raise DailySpendCapReached(f"${spent:.2f} spent in the last 24h (cap ${cap:.2f})")


async def record_call(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float | None = None,
    error: str | None = None,
) -> None:
    error = error[:MAX_ERROR_CHARS] if error else None
    event = _current_event.get()
    if event is not None:
        event.model = model
        event.input_tokens = (event.input_tokens or 0) + input_tokens
        event.output_tokens = (event.output_tokens or 0) + output_tokens
        if cost_usd is not None:
            event.cost_usd = round((event.cost_usd or 0.0) + cost_usd, 6)
        if error:
            event.error = error
        return
    job = _current_job.get()
    try:
        async with async_session() as db:
            db.add(AIUsageEvent(
                endpoint=f"job:{job}" if job else "unattributed",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                error=error,
            ))
            await db.commit()
    except Exception as e:
        print(f"[ai_cost] Failed to record standalone AI usage: {e}")


async def record_response(model: str, data: dict[str, Any]) -> None:
    try:
        input_tokens, output_tokens, searches = extract_usage(data)
        await record_call(model, input_tokens, output_tokens, estimate_cost(model, input_tokens, output_tokens, searches))
    except Exception as e:
        print(f"[ai_cost] Failed to meter AI response: {e}")


async def record_failure(model: str, exc: BaseException) -> None:
    try:
        message = DAILY_SPEND_CAP_ERROR if isinstance(exc, DailySpendCapReached) else (f"{type(exc).__name__}: {exc}".rstrip(": "))
        await record_call(model, error=message)
    except Exception as e:
        print(f"[ai_cost] Failed to record AI failure: {e}")
