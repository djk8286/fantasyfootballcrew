"""
Tests for the AI Co-Commissioner per-league toggle: GET/PUT
/leagues/{id}/ai-settings, and that every AI Co-Commissioner endpoint
actually enforces it (403 when disabled). AIService methods are
monkeypatched where a test needs to get past the gate to prove the
gate itself is what's being tested, not incidentally blocked by the
no-API-key fallback.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.services.auth_service import create_access_token
from app.services.ai_service import AIService
from app.services.ai_commissioner_settings_service import get_ai_commissioner_settings

YEAR = 2026


async def _make_league(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"aisettingscommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="AI Settings Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Only Team", league_id=league.id,
                    owner_id=commissioner.id, roster=[], roster_version=0)
        db.add(team)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"league_id": league.id, "commissioner_id": commissioner.id, "token": token}


async def _disable_ai(db_session_factory, league_id):
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        league.ai_commissioner_settings = {"enabled": False}
        await db.commit()


def test_default_settings_are_enabled():
    class FakeLeague:
        ai_commissioner_settings = None
    assert get_ai_commissioner_settings(FakeLeague())["enabled"] is True


@pytest.mark.asyncio
async def test_get_ai_settings_ungated_returns_default(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    # No auth header at all -- GET is ungated, same house style as best-ball-settings.
    r = await client.get(f"/leagues/{setup['league_id']}/ai-settings")
    assert r.status_code == 200
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_put_ai_settings_commissioner_only(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"aisettingsoutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.put(f"/leagues/{setup['league_id']}/ai-settings", json={"ai_commissioner_settings": {"enabled": False}})
    assert r.status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.put(f"/leagues/{setup['league_id']}/ai-settings", json={"ai_commissioner_settings": {"enabled": False}})
    assert r.status_code == 200
    assert r.json()["ai_commissioner_settings"]["enabled"] is False

    r = await client.get(f"/leagues/{setup['league_id']}/ai-settings")
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_put_ai_settings_rejects_non_bool_enabled(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.put(f"/leagues/{setup['league_id']}/ai-settings", json={"ai_commissioner_settings": {"enabled": "nope"}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_disabling_ai_blocks_every_ai_endpoint(client, db_session_factory, monkeypatch):
    async def spy(*args, **kwargs):
        return "ok"
    monkeypatch.setattr(AIService, "_call_llm", spy)
    monkeypatch.setattr(AIService, "chat", lambda self, **kwargs: spy())

    setup = await _make_league(db_session_factory)
    await _disable_ai(db_session_factory, setup["league_id"])
    client.headers["Authorization"] = f"Bearer {setup['token']}"

    checks = [
        ("POST", f"/leagues/{setup['league_id']}/commissioner/digest/generate?week=1&year={YEAR}", None),
        ("GET", f"/leagues/{setup['league_id']}/commissioner/digest?week=1&year={YEAR}", None),
        ("GET", f"/leagues/{setup['league_id']}/commissioner/health", None),
        ("GET", f"/leagues/{setup['league_id']}/commissioner/insights", None),
        ("GET", f"/leagues/{setup['league_id']}/commissioner/schedule-insights", None),
        ("POST", f"/leagues/{setup['league_id']}/commissioner/messages/draft", {"message_type": "general", "tone": "professional"}),
        ("POST", f"/leagues/{setup['league_id']}/commissioner/messages/send", {"message_type": "general", "content": "hi"}),
        ("GET", f"/leagues/{setup['league_id']}/commissioner/chat", None),
        ("POST", f"/leagues/{setup['league_id']}/commissioner/chat", {"message": "hi"}),
    ]
    for method, url, body in checks:
        if method == "GET":
            r = await client.get(url)
        else:
            r = await client.post(url, json=body)
        assert r.status_code == 403, f"{method} {url} expected 403, got {r.status_code}: {r.text}"
        assert "disabled" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_clear_chat_still_works_while_ai_disabled(client, db_session_factory):
    """Deliberate exception -- clearing stored history costs nothing
    and isn't 'using' an AI feature, so it stays available regardless
    of the toggle."""
    setup = await _make_league(db_session_factory)
    await _disable_ai(db_session_factory, setup["league_id"])
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.delete(f"/leagues/{setup['league_id']}/commissioner/chat")
    assert r.status_code == 200
