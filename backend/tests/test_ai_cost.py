"""
Tests for AI cost tracking (ai_cost_service + the metered provider path in
ai_service) and the optional global daily spend cap, plus the admin
/admin/ai-cost endpoint built on the new AIUsageEvent cost fields.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.ai_usage_event import AIUsageEvent
from app.models.user import User
from app.services import ai_cost_service
from app.services.ai_service import AIService, AI_DAILY_BUDGET_REACHED, AI_TEMPORARILY_UNAVAILABLE, OPENAI_MODEL
from app.services.auth_service import create_access_token
from tests.test_admin import _make_user

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"
OPENAI_RESPONSES = "https://api.openai.com/v1/responses"
ANTHROPIC = "https://api.anthropic.com/v1/messages"


@pytest.fixture
def standalone_db(db_session_factory, monkeypatch):
    """Route ai_cost_service's own-session writes/reads to the test DB."""
    monkeypatch.setattr(ai_cost_service, "async_session", db_session_factory)
    return db_session_factory


async def _events(factory):
    async with factory() as db:
        return (await db.execute(select(AIUsageEvent).order_by(AIUsageEvent.created_at))).scalars().all()


def test_estimate_cost_uses_price_table_and_flags_unpriced():
    # gpt-5.6-luna: $0.20 / $1.20 per 1M tokens
    assert ai_cost_service.estimate_cost(OPENAI_MODEL, 1_000_000, 1_000_000) == pytest.approx(1.40)
    assert ai_cost_service.estimate_cost(OPENAI_MODEL, 1000, 500, web_searches=2) == pytest.approx(
        (1000 * 0.20 + 500 * 1.20) / 1e6 + 2 * settings.AI_WEB_SEARCH_COST_PER_CALL)
    assert ai_cost_service.estimate_cost("some-new-model", 10, 10) is None


def test_extract_usage_handles_all_three_provider_shapes():
    assert ai_cost_service.extract_usage({"usage": {"prompt_tokens": 11, "completion_tokens": 7}}) == (11, 7, 0)
    assert ai_cost_service.extract_usage({"usage": {"input_tokens": 5, "output_tokens": 3}}) == (5, 3, 0)
    responses = {"usage": {"input_tokens": 100, "output_tokens": 40},
                 "output": [{"type": "web_search_call"}, {"type": "web_search_call"}, {"type": "message"}]}
    assert ai_cost_service.extract_usage(responses) == (100, 40, 2)
    assert ai_cost_service.extract_usage({}) == (0, 0, 0)


@pytest.mark.asyncio
async def test_background_call_writes_standalone_row_tagged_with_job(standalone_db, httpx_mock, monkeypatch):
    from app.services.job_run_service import run_job
    from app.services import job_run_service
    monkeypatch.setattr(job_run_service, "async_session", standalone_db)  # job row too
    httpx_mock.add_response(url=OPENAI_CHAT, json={
        "choices": [{"message": {"content": "recap"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})

    async def job():
        return await AIService(api_key="k", provider="openai")._call_llm("prompt")

    assert await run_job("team_recaps", job) == "recap"
    rows = await _events(standalone_db)
    assert len(rows) == 1
    r = rows[0]
    assert r.endpoint == "job:team_recaps" and r.model == OPENAI_MODEL
    assert (r.input_tokens, r.output_tokens) == (1000, 200)
    assert r.cost_usd == pytest.approx((1000 * 0.20 + 200 * 1.20) / 1e6)
    assert r.error is None


@pytest.mark.asyncio
async def test_provider_failure_is_recorded_and_still_returns_friendly_string(standalone_db, httpx_mock):
    httpx_mock.add_response(url=ANTHROPIC, status_code=529, json={"error": "overloaded"})
    out = await AIService(api_key="k", provider="anthropic")._call_llm("prompt")
    assert out == AI_TEMPORARILY_UNAVAILABLE
    rows = await _events(standalone_db)
    assert len(rows) == 1 and rows[0].endpoint == "unattributed"
    assert rows[0].model == "claude-haiku-4-5-20251001"
    assert rows[0].error.startswith("HTTPStatusError")
    assert rows[0].cost_usd is None


@pytest.mark.asyncio
async def test_request_call_attaches_tokens_and_cost_to_the_requests_own_row(client, db_session_factory, standalone_db, httpx_mock, monkeypatch):
    """POST /ai/bet goes through OpenAI's Responses API with web search.
    The request's AIUsageEvent (endpoint="bet") gets the cost -- no
    second standalone row."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    httpx_mock.add_response(url=OPENAI_RESPONSES, json={
        "usage": {"input_tokens": 2000, "output_tokens": 500},
        "output": [{"type": "web_search_call"}, {"type": "message", "content": [{"type": "output_text", "text": "Take the under."}]}],
    })
    user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/bet", json={"prompt": "Over 44.5 in KC-BUF?"})
    assert r.status_code == 200 and "under" in r.json()["analysis"]

    rows = await _events(db_session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.endpoint == "bet" and row.user_id == user.id
    assert (row.model, row.input_tokens, row.output_tokens) == (OPENAI_MODEL, 2000, 500)
    assert row.cost_usd == pytest.approx((2000 * 0.20 + 500 * 1.20) / 1e6 + settings.AI_WEB_SEARCH_COST_PER_CALL)


@pytest.mark.asyncio
async def test_spend_cap_blocks_provider_call_gracefully(standalone_db, httpx_mock, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_SPEND_CAP_USD", 1.00)
    async with standalone_db() as db:
        db.add(AIUsageEvent(endpoint="chat", model=OPENAI_MODEL, cost_usd=0.75))
        db.add(AIUsageEvent(endpoint="chat", model=OPENAI_MODEL, cost_usd=0.30))
        old = AIUsageEvent(endpoint="chat", model=OPENAI_MODEL, cost_usd=50.0)
        old.created_at = datetime.now(timezone.utc) - timedelta(hours=30)  # outside the rolling 24h
        db.add(old)
        await db.commit()

    out = await AIService(api_key="k", provider="openai")._call_llm("prompt")
    assert out == AI_DAILY_BUDGET_REACHED
    assert httpx_mock.get_requests() == []  # never reached the provider
    blocked = [e for e in await _events(standalone_db) if e.error == ai_cost_service.DAILY_SPEND_CAP_ERROR]
    assert len(blocked) == 1 and blocked[0].cost_usd is None


@pytest.mark.asyncio
async def test_under_cap_calls_proceed(standalone_db, httpx_mock, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_SPEND_CAP_USD", 5.00)
    httpx_mock.add_response(url=OPENAI_CHAT, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})
    assert await AIService(api_key="k", provider="openai")._call_llm("prompt") == "ok"


@pytest.mark.asyncio
async def test_admin_ai_cost_endpoint(client, db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "AI_DAILY_SPEND_CAP_USD", 2.0)
    admin, token = await _make_user(db_session_factory, is_admin=True)
    spender, _ = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        db.add_all([
            AIUsageEvent(endpoint="bet", user_id=spender.id, model=OPENAI_MODEL, input_tokens=1000, output_tokens=100, cost_usd=0.50),
            AIUsageEvent(endpoint="chat", user_id=admin.id, model=OPENAI_MODEL, input_tokens=10, output_tokens=10, cost_usd=0.10),
            AIUsageEvent(endpoint="job:team_recaps", model="mystery-model", input_tokens=5, output_tokens=5, cost_usd=None),
            AIUsageEvent(endpoint="chat", model=OPENAI_MODEL, error="daily_spend_cap"),
            AIUsageEvent(endpoint="lineup", user_id=spender.id),  # pre-cost-tracking row
        ])
        await db.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/ai-cost")
    assert r.status_code == 200
    d = r.json()
    assert d["calls"] == 5
    assert d["cost_usd"] == pytest.approx(0.60) and d["cost_24h_usd"] == pytest.approx(0.60)
    assert d["input_tokens"] == 1015 and d["output_tokens"] == 115
    assert d["unpriced_calls"] == 1
    assert d["errors_24h"] == 1
    assert d["spend_cap"] == {"cap_usd": 2.0, "spent_24h_usd": pytest.approx(0.60), "reached": False, "blocked_calls_24h": 1}
    assert len(d["daily"]) == 1 and d["daily"][0]["cost_usd"] == pytest.approx(0.60)
    assert d["top_users"][0]["username"] == spender.username
    assert d["top_users"][0]["cost_usd"] == pytest.approx(0.50) and d["top_users"][0]["calls"] == 2
    assert d["by_feature"][0]["endpoint"] == "bet"
    assert {m["model"] for m in d["by_model"]} == {OPENAI_MODEL, "mystery-model"}


@pytest.mark.asyncio
async def test_admin_ai_cost_requires_admin(client, db_session_factory):
    _u, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    assert (await client.get("/admin/ai-cost")).status_code == 403
