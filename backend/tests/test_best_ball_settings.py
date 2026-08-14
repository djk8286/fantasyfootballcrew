"""
Tests for the Best-Ball settings API (Phase 6 Step 3) --
GET/PUT /leagues/{id}/best-ball-settings and
GET /leagues/{id}/management-window. Scoring integration itself
(calculate_week actually using the optimal lineup) is covered
separately in test_best_ball_scoring.py once Step 4 lands. Window math
itself is covered in test_best_ball_window.py (pure functions).
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueType
from app.services.auth_service import create_access_token
from app.services.best_ball_service import DEFAULT_BEST_BALL_SETTINGS, is_window_open


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, league_type=LeagueType.STANDARD):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Best Ball Settings Test League", commissioner_id=commissioner_id,
                         league_type=league_type, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_get_best_ball_settings_defaults(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    r = await client.get(f"/leagues/{league_id}/best-ball-settings")
    assert r.status_code == 200
    assert r.json() == DEFAULT_BEST_BALL_SETTINGS


@pytest.mark.asyncio
async def test_commissioner_can_set_best_ball_settings(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    payload = {"enabled": True, "lock_weekday": 2, "lock_hour": 18, "reopen_weekday": 1, "reopen_hour": 9}
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": payload})
    assert r.status_code == 200
    assert r.json()["best_ball_settings"] == payload

    r = await client.get(f"/leagues/{league_id}/best-ball-settings")
    assert r.json() == payload


@pytest.mark.asyncio
async def test_put_merges_onto_defaults(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"lock_hour": 22}})
    assert r.status_code == 200
    body = r.json()["best_ball_settings"]
    assert body["lock_hour"] == 22
    assert body["reopen_weekday"] == DEFAULT_BEST_BALL_SETTINGS["reopen_weekday"]
    assert body["enabled"] is False


@pytest.mark.asyncio
async def test_non_commissioner_cannot_update(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"enabled": True}})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_cannot_update(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"enabled": True}})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_lock_weekday_out_of_range_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"lock_weekday": 7}})
    assert r.status_code == 422
    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"lock_weekday": -1}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_lock_hour_out_of_range_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"reopen_hour": 24}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_enabling_works_for_any_league_type(client, db_session_factory):
    """Bolt-on flag, same as salary-cap -- works on any league_type."""
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id, league_type=LeagueType.CONFERENCE)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"enabled": True}})
    assert r.status_code == 200


# ─── management-window ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_management_window_disabled_is_always_open(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    r = await client.get(f"/leagues/{league_id}/management-window")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["is_open"] is True
    assert body["next_transition_at"] is None
    assert body["next_transition_type"] is None


@pytest.mark.asyncio
async def test_management_window_enabled_reflects_real_clock(client, db_session_factory):
    from datetime import datetime, timezone

    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    await client.put(f"/leagues/{league_id}/best-ball-settings", json={"best_ball_settings": {"enabled": True}})

    r = await client.get(f"/leagues/{league_id}/management-window")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert isinstance(body["is_open"], bool)
    assert body["next_transition_type"] in ("opens", "closes")
    expected_open = is_window_open(datetime.now(timezone.utc).replace(tzinfo=None), DEFAULT_BEST_BALL_SETTINGS)
    assert body["is_open"] == expected_open
