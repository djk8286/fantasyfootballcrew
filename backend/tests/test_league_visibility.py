"""
Tests for League.visibility -- the actual privacy gate that previously
didn't exist at all (every league was 100% publicly listable regardless
of any setting). See radiant-booping-eagle plan, Phase 1 Step 2.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueVisibility
from app.services.auth_service import create_access_token


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, name, visibility):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name=name, commissioner_id=commissioner_id,
                         visibility=visibility, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_new_league_defaults_to_open(client, db_session_factory):
    _user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/leagues", json={"name": "Default Vis League"})
    assert r.status_code == 201
    assert r.json()["visibility"] == "open"


@pytest.mark.asyncio
async def test_create_league_with_explicit_visibility(client, db_session_factory):
    _user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/leagues", json={"name": "Private League", "visibility": "private"})
    assert r.status_code == 201
    assert r.json()["visibility"] == "private"


@pytest.mark.asyncio
async def test_public_listing_excludes_private_leagues(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    await _make_league(db_session_factory, user.id, "Open League", LeagueVisibility.OPEN)
    await _make_league(db_session_factory, user.id, "Invite League", LeagueVisibility.INVITE_ONLY)
    await _make_league(db_session_factory, user.id, "Private League", LeagueVisibility.PRIVATE)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues")
    assert r.status_code == 200
    names = {l["name"] for l in r.json()}
    assert "Open League" in names
    assert "Invite League" in names
    assert "Private League" not in names


@pytest.mark.asyncio
async def test_mine_listing_includes_own_private_leagues(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    await _make_league(db_session_factory, user.id, "My Private League", LeagueVisibility.PRIVATE)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues?mine=true")
    assert r.status_code == 200
    names = {l["name"] for l in r.json()}
    assert "My Private League" in names


@pytest.mark.asyncio
async def test_public_listing_never_leaks_someone_elses_private_league(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    viewer, viewer_token = await _make_user(db_session_factory)
    await _make_league(db_session_factory, owner.id, "Someone Elses Private League", LeagueVisibility.PRIVATE)

    client.headers["Authorization"] = f"Bearer {viewer_token}"
    r = await client.get("/leagues")
    names = {l["name"] for l in r.json()}
    assert "Someone Elses Private League" not in names


@pytest.mark.asyncio
async def test_commissioner_can_update_visibility(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id, "Changeable League", LeagueVisibility.OPEN)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.patch(f"/leagues/{league_id}", json={"visibility": "invite_only"})
    assert r.status_code == 200
    assert r.json()["visibility"] == "invite_only"

    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["visibility"] == "invite_only"


@pytest.mark.asyncio
async def test_non_commissioner_cannot_update_visibility(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, "Not Yours League", LeagueVisibility.OPEN)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.patch(f"/leagues/{league_id}", json={"visibility": "private"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_wanted_board_hidden_toggle(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id, "Board League", LeagueVisibility.OPEN)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["wanted_board_hidden"] is False

    r = await client.patch(f"/leagues/{league_id}", json={"wanted_board_hidden": True})
    assert r.status_code == 200
    assert r.json()["wanted_board_hidden"] is True
