"""
Tests for Phase 8 ("AI-Assisted Commissioner Tools") Step 4 --
POST/GET /leagues/{id}/commissioner/digest[/generate]. AIService._call_llm
is monkeypatched to a spy throughout (same technique test_ai_service.py/
test_commissioner_digest_service.py already use) -- no real network call.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.services.auth_service import create_access_token
from app.services.ai_service import AIService

WEEK, YEAR = 3, 2026


async def _make_league(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"digestepcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Digest Endpoint Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"token": token, "commissioner_id": commissioner.id, "league_id": league.id,
                "db_session_factory": db_session_factory}


@pytest.mark.asyncio
async def test_generate_digest_creates_and_returns_content(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "POWER RANKINGS\n1. Nobody yet"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/digest/generate",
                           params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
    body = r.json()
    assert body["content"].startswith("POWER RANKINGS")
    assert body["week"] == WEEK
    assert body["year"] == YEAR


@pytest.mark.asyncio
async def test_generate_digest_requires_commissioner(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "ok"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league(db_session_factory)
    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"digestoutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/digest/generate",
                           params={"week": WEEK, "year": YEAR})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_digest_before_generation_404s(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/digest", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_regenerate_updates_in_place_and_get_reflects_it(client, db_session_factory, monkeypatch):
    call_count = {"n": 0}

    async def spy(self, prompt):
        call_count["n"] += 1
        return f"VERSION {call_count['n']}"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"

    r1 = await client.post(f"/leagues/{setup['league_id']}/commissioner/digest/generate",
                            params={"week": WEEK, "year": YEAR})
    assert r1.json()["content"] == "VERSION 1"

    r2 = await client.post(f"/leagues/{setup['league_id']}/commissioner/digest/generate",
                            params={"week": WEEK, "year": YEAR})
    assert r2.json()["content"] == "VERSION 2"

    r_get = await client.get(f"/leagues/{setup['league_id']}/commissioner/digest", params={"week": WEEK, "year": YEAR})
    assert r_get.status_code == 200
    assert r_get.json()["content"] == "VERSION 2"


@pytest.mark.asyncio
async def test_get_digest_after_generation_makes_zero_additional_llm_calls(client, db_session_factory, monkeypatch):
    call_count = {"n": 0}

    async def spy(self, prompt):
        call_count["n"] += 1
        return "cached content"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    await client.post(f"/leagues/{setup['league_id']}/commissioner/digest/generate",
                       params={"week": WEEK, "year": YEAR})
    assert call_count["n"] == 1

    for _ in range(3):
        r = await client.get(f"/leagues/{setup['league_id']}/commissioner/digest", params={"week": WEEK, "year": YEAR})
        assert r.status_code == 200
    assert call_count["n"] == 1  # GET never calls the LLM
