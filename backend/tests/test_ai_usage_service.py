"""
Tests for ai_usage_service.check_and_record_ai_usage -- the per-league
daily cap on real LLM-spend calls, tracked in the database (not the
in-process per-IP rate limiter).
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.ai_usage_event import AIUsageEvent
from app.services.auth_service import create_access_token
from app.services.ai_service import AIService
from app.services.ai_usage_service import check_and_record_ai_usage, DAILY_AI_LIMIT_PER_LEAGUE

YEAR = 2026


async def _make_league(db_session_factory):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Usage Cap Test League", commissioner_id=str(uuid.uuid4()),
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


async def _make_league_with_commissioner(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"usagecommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Usage Cap Endpoint League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"league_id": league.id, "token": token}


@pytest.mark.asyncio
async def test_records_a_call_and_allows_it_under_the_limit(db_session_factory):
    league_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        await check_and_record_ai_usage(league_id, "digest_generate", db)
        await db.commit()

    async with db_session_factory() as db:
        count = await db.scalar(select(func.count(AIUsageEvent.id)).where(AIUsageEvent.league_id == league_id))
    assert count == 1


@pytest.mark.asyncio
async def test_raises_429_once_daily_limit_is_reached(db_session_factory):
    league_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        for _ in range(DAILY_AI_LIMIT_PER_LEAGUE):
            db.add(AIUsageEvent(league_id=league_id, endpoint="chat"))
        await db.commit()

    async with db_session_factory() as db:
        with pytest.raises(Exception) as exc_info:
            await check_and_record_ai_usage(league_id, "chat", db)
        assert "429" in str(exc_info.value) or getattr(exc_info.value, "status_code", None) == 429


@pytest.mark.asyncio
async def test_events_older_than_24h_do_not_count_toward_the_limit(db_session_factory):
    league_id = await _make_league(db_session_factory)
    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    async with db_session_factory() as db:
        for _ in range(DAILY_AI_LIMIT_PER_LEAGUE):
            db.add(AIUsageEvent(league_id=league_id, endpoint="chat", created_at=old_time))
        await db.commit()

    # All prior events are outside the 24h window -- this call should
    # succeed (not raise) and add exactly one fresh row.
    async with db_session_factory() as db:
        await check_and_record_ai_usage(league_id, "chat", db)
        await db.commit()

    async with db_session_factory() as db:
        recent_count = await db.scalar(
            select(func.count(AIUsageEvent.id)).where(
                AIUsageEvent.league_id == league_id,
                AIUsageEvent.created_at >= datetime.now(timezone.utc) - timedelta(hours=24),
            )
        )
    assert recent_count == 1


@pytest.mark.asyncio
async def test_limit_is_scoped_per_league_not_global(db_session_factory):
    league_a = await _make_league(db_session_factory)
    league_b = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        for _ in range(DAILY_AI_LIMIT_PER_LEAGUE):
            db.add(AIUsageEvent(league_id=league_a, endpoint="chat"))
        await db.commit()

    # League A is at its cap; League B, untouched, must still be allowed.
    async with db_session_factory() as db:
        await check_and_record_ai_usage(league_b, "chat", db)
        await db.commit()

    async with db_session_factory() as db:
        count_b = await db.scalar(select(func.count(AIUsageEvent.id)).where(AIUsageEvent.league_id == league_b))
    assert count_b == 1


# ─── Wired into the real endpoints (not just the service in isolation) ──

@pytest.mark.asyncio
async def test_digest_generate_429s_once_daily_cap_reached(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "content"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league_with_commissioner(db_session_factory)
    async with db_session_factory() as db:
        for _ in range(DAILY_AI_LIMIT_PER_LEAGUE):
            db.add(AIUsageEvent(league_id=setup["league_id"], endpoint="digest_generate"))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/digest/generate",
                           params={"week": 1, "year": YEAR})
    assert r.status_code == 429
    assert "daily" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_chat_post_429s_once_daily_cap_reached(client, db_session_factory, monkeypatch):
    async def spy(self, **kwargs):
        return "ok"
    monkeypatch.setattr(AIService, "chat", spy)

    setup = await _make_league_with_commissioner(db_session_factory)
    async with db_session_factory() as db:
        for _ in range(DAILY_AI_LIMIT_PER_LEAGUE):
            db.add(AIUsageEvent(league_id=setup["league_id"], endpoint="chat"))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/chat", json={"message": "hi"})
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_message_draft_429s_and_the_usage_row_still_persists_across_the_request(client, db_session_factory, monkeypatch):
    """Regression pin for the specific bug found while wiring this up:
    draft_message() never commits anything itself, so the usage-cap
    row from a call that's actually allowed through must be committed
    explicitly by the endpoint, or it silently never counts toward the
    cap on the next request."""
    async def spy(self, prompt):
        return "content"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league_with_commissioner(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"

    r1 = await client.post(f"/leagues/{setup['league_id']}/commissioner/messages/draft",
                            json={"message_type": "general", "tone": "professional"})
    assert r1.status_code == 200

    async with db_session_factory() as db:
        count = await db.scalar(select(func.count(AIUsageEvent.id)).where(AIUsageEvent.league_id == setup["league_id"]))
    assert count == 1  # would be 0 if the endpoint's explicit commit were missing

    async with db_session_factory() as db:
        for _ in range(DAILY_AI_LIMIT_PER_LEAGUE - 1):
            db.add(AIUsageEvent(league_id=setup["league_id"], endpoint="message_draft"))
        await db.commit()

    r2 = await client.post(f"/leagues/{setup['league_id']}/commissioner/messages/draft",
                            json={"message_type": "general", "tone": "professional"})
    assert r2.status_code == 429
