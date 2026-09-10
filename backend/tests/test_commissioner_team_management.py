"""
Tests for commissioner-side team ownership overrides: remove-owner,
remove-co-owner, assign-owner, assign-co-owner (app/api/v1/teams.py).
Before these existed, the only way anyone ended up owning a team was
self-service (claim_team/claim_co_owner/accept_invite's auto-claim) --
a commissioner had no way to fix a wrong claim or hand-assign teams.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueVisibility, LeagueType
from app.models.team import Team
from app.services.auth_service import create_access_token


async def _make_user(db_session_factory, username=None):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=username or f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, league_type=LeagueType.STANDARD):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Team Mgmt Test League", commissioner_id=commissioner_id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={}, league_type=league_type)
        db.add(league)
        await db.commit()
        return league.id


async def _make_team(db_session_factory, league_id, owner_id=None, co_owner_id=None, is_cpu=False, name="Test Team"):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name=name, league_id=league_id,
                    owner_id=owner_id, co_owner_id=co_owner_id, is_cpu=is_cpu, roster=[])
        db.add(team)
        await db.commit()
        return team.id


# ─── remove-owner ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remove_owner_requires_commissioner(client, db_session_factory):
    commissioner, _ = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/teams/{team_id}/remove-owner")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_remove_owner_with_no_co_owner_flips_to_cpu(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/remove-owner")
    assert r.status_code == 200
    body = r.json()
    assert body["owner_id"] is None
    assert body["is_cpu"] is True


@pytest.mark.asyncio
async def test_remove_owner_with_co_owner_promotes_co_owner(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    co_owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id, co_owner_id=co_owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/remove-owner")
    assert r.status_code == 200
    body = r.json()
    assert body["owner_id"] == co_owner.id
    assert body["co_owner_id"] is None
    assert body["is_cpu"] is False


@pytest.mark.asyncio
async def test_remove_owner_errors_if_no_owner(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, is_cpu=True)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/remove-owner")
    assert r.status_code == 400


# ─── remove-co-owner ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remove_co_owner_requires_commissioner(client, db_session_factory):
    commissioner, _ = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    co_owner, _ = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id, co_owner_id=co_owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/teams/{team_id}/remove-co-owner")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_remove_co_owner_clears_it_leaves_owner_alone(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    co_owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id, co_owner_id=co_owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/remove-co-owner")
    assert r.status_code == 200
    body = r.json()
    assert body["co_owner_id"] is None
    assert body["owner_id"] == owner.id


@pytest.mark.asyncio
async def test_remove_co_owner_errors_if_none(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/remove-co-owner")
    assert r.status_code == 400


# ─── assign-owner ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_owner_requires_commissioner(client, db_session_factory):
    commissioner, _ = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, is_cpu=True)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/teams/{team_id}/assign-owner", json={"identifier": target.username})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_assign_owner_by_username(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory, username="TargetPlayer")
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, is_cpu=True)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-owner", json={"identifier": "TargetPlayer"})
    assert r.status_code == 200
    body = r.json()
    assert body["owner_id"] == target.id
    assert body["is_cpu"] is False
    assert body["name"] == "TargetPlayer's Team"


@pytest.mark.asyncio
async def test_assign_owner_by_email(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, is_cpu=True)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-owner", json={"identifier": target.email})
    assert r.status_code == 200
    assert r.json()["owner_id"] == target.id


@pytest.mark.asyncio
async def test_assign_owner_fails_if_team_not_cpu(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-owner", json={"identifier": target.username})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_assign_owner_fails_if_user_not_found(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id)
    team_id = await _make_team(db_session_factory, league_id, is_cpu=True)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-owner", json={"identifier": "nobody-by-this-name"})
    assert r.status_code == 404


# ─── assign-co-owner ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_co_owner_by_username(client, db_session_factory):
    # Co-Owner (2-Man Teams) is TWO_MAN-league-only -- see teams.py's
    # league_type gate added alongside this test's update.
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory, username="CoOwnerPlayer")
    league_id = await _make_league(db_session_factory, commissioner.id, league_type=LeagueType.TWO_MAN)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-co-owner", json={"identifier": "CoOwnerPlayer"})
    assert r.status_code == 200
    assert r.json()["co_owner_id"] == target.id


@pytest.mark.asyncio
async def test_assign_co_owner_blocked_outside_two_man_league(client, db_session_factory):
    """Co-Owner (2-Man Teams) is hidden and non-functional everywhere
    except TWO_MAN leagues -- see teams.py's league_type gate."""
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id, league_type=LeagueType.STANDARD)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-co-owner", json={"identifier": target.username})
    assert r.status_code == 400
    assert "2-Man" in r.json()["detail"]


@pytest.mark.asyncio
async def test_assign_co_owner_fails_if_already_has_one(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    existing_co, _ = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id, league_type=LeagueType.TWO_MAN)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id, co_owner_id=existing_co.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-co-owner", json={"identifier": target.username})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_assign_co_owner_fails_if_team_still_cpu(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id, league_type=LeagueType.TWO_MAN)
    team_id = await _make_team(db_session_factory, league_id, is_cpu=True)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-co-owner", json={"identifier": target.username})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_assign_co_owner_fails_if_target_is_owner(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commissioner.id, league_type=LeagueType.TWO_MAN)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/teams/{team_id}/assign-co-owner", json={"identifier": owner.username})
    assert r.status_code == 400
