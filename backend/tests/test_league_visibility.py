"""
Tests for League.visibility -- the actual privacy gate that previously
didn't exist at all (every league was 100% publicly listable regardless
of any setting). See radiant-booping-eagle plan, Phase 1 Step 2.
"""
import uuid
import pytest
from app.models.user import User
from app.models.team import Team
from app.models.league import League, LeagueVisibility, LeagueType
from app.services.auth_service import create_access_token


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, name, visibility,
                        league_type=LeagueType.STANDARD, max_teams=12, wanted_board_hidden=False):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name=name, commissioner_id=commissioner_id,
                         visibility=visibility, league_type=league_type, max_teams=max_teams,
                         wanted_board_hidden=wanted_board_hidden, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


async def _add_team(db_session_factory, league_id, name):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name=name, league_id=league_id, roster=[])
        db.add(team)
        await db.commit()


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
async def test_filter_by_league_type(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    await _make_league(db_session_factory, user.id, "A Standard League", LeagueVisibility.OPEN, league_type=LeagueType.STANDARD)
    await _make_league(db_session_factory, user.id, "A Conference League", LeagueVisibility.OPEN, league_type=LeagueType.CONFERENCE)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues?league_type=conference")
    names = {l["name"] for l in r.json()}
    assert "A Conference League" in names
    assert "A Standard League" not in names


@pytest.mark.asyncio
async def test_open_only_filters_full_leagues(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    full_id = await _make_league(db_session_factory, user.id, "Full League", LeagueVisibility.OPEN, max_teams=1)
    await _add_team(db_session_factory, full_id, "Only Team")
    await _make_league(db_session_factory, user.id, "Roomy League", LeagueVisibility.OPEN, max_teams=2)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues?open_only=true")
    names = {l["name"] for l in r.json()}
    assert "Roomy League" in names
    assert "Full League" not in names


@pytest.mark.asyncio
async def test_wanted_board_only_excludes_private_hidden_and_full(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    await _make_league(db_session_factory, user.id, "Wanted Open League", LeagueVisibility.OPEN, max_teams=4)
    await _make_league(db_session_factory, user.id, "Wanted Invite League", LeagueVisibility.INVITE_ONLY, max_teams=4)
    await _make_league(db_session_factory, user.id, "Hidden From Board League", LeagueVisibility.OPEN, max_teams=4, wanted_board_hidden=True)
    await _make_league(db_session_factory, user.id, "Private Never Listed League", LeagueVisibility.PRIVATE, max_teams=4)
    full_id = await _make_league(db_session_factory, user.id, "Wanted Full League", LeagueVisibility.OPEN, max_teams=1)
    await _add_team(db_session_factory, full_id, "Only Team")

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues?wanted_board_only=true")
    names = {l["name"] for l in r.json()}
    assert names == {"Wanted Open League", "Wanted Invite League"}


@pytest.mark.asyncio
async def test_sort_by_name(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    await _make_league(db_session_factory, user.id, "Zeta League", LeagueVisibility.OPEN)
    await _make_league(db_session_factory, user.id, "Alpha League", LeagueVisibility.OPEN)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues?sort=name")
    names = [l["name"] for l in r.json()]
    assert names.index("Alpha League") < names.index("Zeta League")


@pytest.mark.asyncio
async def test_sort_by_open_spots(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    lots_open_id = await _make_league(db_session_factory, user.id, "Lots Open League", LeagueVisibility.OPEN, max_teams=10)
    few_open_id = await _make_league(db_session_factory, user.id, "Few Open League", LeagueVisibility.OPEN, max_teams=2)
    await _add_team(db_session_factory, few_open_id, "T1")

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues?sort=open_spots")
    names = [l["name"] for l in r.json()]
    assert names.index("Lots Open League") < names.index("Few Open League")


@pytest.mark.asyncio
async def test_invalid_sort_rejected(client, db_session_factory):
    _user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/leagues?sort=bogus")
    assert r.status_code == 422


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
