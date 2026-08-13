"""
Tests for the Rivalry Week settings API (Phase 3 Step 3, "Enhanced
Conference/Rivalry") -- GET/PUT /leagues/{id}/rivalry-week-settings.
Scoring integration itself (calculate_week actually paying out the
bonus) is covered separately in test_rivalry_week.py once Step 4 lands.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueType
from app.services.auth_service import create_access_token


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, league_type=LeagueType.CONFERENCE):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Rivalry Settings Test League", commissioner_id=commissioner_id,
                         league_type=league_type, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_get_rivalry_week_settings_defaults(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    r = await client.get(f"/leagues/{league_id}/rivalry-week-settings")
    assert r.status_code == 200
    assert r.json() == {"enabled": False, "week": None, "bonus_value": 0.0}


@pytest.mark.asyncio
async def test_commissioner_can_set_rivalry_week_settings(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"enabled": True, "week": 5, "bonus_value": 7.5}})
    assert r.status_code == 200
    assert r.json()["rivalry_week_settings"] == {"enabled": True, "week": 5, "bonus_value": 7.5}

    r = await client.get(f"/leagues/{league_id}/rivalry-week-settings")
    assert r.json() == {"enabled": True, "week": 5, "bonus_value": 7.5}


@pytest.mark.asyncio
async def test_put_merges_onto_defaults(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    # Only sends bonus_value -- enabled/week should merge from defaults.
    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"bonus_value": 3.0}})
    assert r.status_code == 200
    assert r.json()["rivalry_week_settings"] == {"enabled": False, "week": None, "bonus_value": 3.0}


@pytest.mark.asyncio
async def test_non_commissioner_cannot_update_rivalry_week_settings(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"enabled": True, "week": 3, "bonus_value": 5.0}})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_enabling_rejected_for_non_conference_league(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id, league_type=LeagueType.STANDARD)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"enabled": True, "week": 3, "bonus_value": 5.0}})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_disabling_allowed_for_non_conference_league(client, db_session_factory):
    """Storing an unused/disabled config on a non-conference league is
    harmless -- only *enabling* it there is rejected."""
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id, league_type=LeagueType.STANDARD)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"enabled": False, "week": None, "bonus_value": 0.0}})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_bad_week_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"enabled": True, "week": 0, "bonus_value": 5.0}})
    assert r.status_code == 422

    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"enabled": True, "week": None, "bonus_value": 5.0}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_negative_bonus_value_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/rivalry-week-settings",
                          json={"rivalry_week_settings": {"enabled": True, "week": 3, "bonus_value": -1.0}})
    assert r.status_code == 422
