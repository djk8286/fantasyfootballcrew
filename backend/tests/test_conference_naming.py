"""
Tests for conference custom naming (Phase 3 Step 2, "Enhanced
Conference/Rivalry") -- previously conferences were hardcoded to "A"/"B"
everywhere with no commissioner-facing naming at all.
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
        league = League(id=str(uuid.uuid4()), name="Naming Test League", commissioner_id=commissioner_id,
                         league_type=league_type, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_commissioner_can_set_conference_names(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.patch(f"/leagues/{league_id}", json={"conference_a_name": "The North", "conference_b_name": "The South"})
    assert r.status_code == 200
    assert r.json()["conference_a_name"] == "The North"
    assert r.json()["conference_b_name"] == "The South"

    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["conference_a_name"] == "The North"
    assert r.json()["conference_b_name"] == "The South"


@pytest.mark.asyncio
async def test_empty_string_clears_conference_name(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    await client.patch(f"/leagues/{league_id}", json={"conference_a_name": "The North"})
    r = await client.patch(f"/leagues/{league_id}", json={"conference_a_name": ""})
    assert r.status_code == 200
    assert r.json()["conference_a_name"] is None


@pytest.mark.asyncio
async def test_conference_name_over_max_length_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.patch(f"/leagues/{league_id}", json={"conference_a_name": "x" * 41})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_conference_names_settable_harmlessly_on_non_conference_league(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id, league_type=LeagueType.STANDARD)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.patch(f"/leagues/{league_id}", json={"conference_a_name": "The North"})
    assert r.status_code == 200
    assert r.json()["conference_a_name"] == "The North"


@pytest.mark.asyncio
async def test_non_commissioner_cannot_set_conference_names(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.patch(f"/leagues/{league_id}", json={"conference_a_name": "The North"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_new_league_has_no_conference_names_by_default(client, db_session_factory):
    _user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/leagues", json={"name": "Fresh League", "league_type": "conference"})
    assert r.status_code == 201
    assert r.json()["conference_a_name"] is None
    assert r.json()["conference_b_name"] is None
