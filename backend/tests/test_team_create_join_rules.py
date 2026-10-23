"""
POST /teams follows the same join rules as claim_team/claim_co_owner:
OPEN leagues are open to any logged-in user; INVITE_ONLY and PRIVATE
leagues need the commissioner role, an accepted invite or an approved
join request. It also respects max_teams and doesn't take a co_owner_id
(co-owners join through claim-co-owner / assign-co-owner).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.limiter import limiter
from app.models.league import League, LeagueType, LeagueVisibility
from app.models.league_invite import InviteStatus, LeagueInvite
from app.models.league_join_request import JoinRequestStatus, LeagueJoinRequest
from app.models.team import Team
from app.models.user import User
from app.services.auth_service import create_access_token


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


async def _make_user(f):
    async with f() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        return user, create_access_token({"sub": user.id, "email": user.email})


async def _make_league(f, commissioner_id, visibility, max_teams=12,
                       league_type=LeagueType.STANDARD, co_commissioner_ids=None):
    async with f() as db:
        league = League(id=str(uuid.uuid4()), name="Join Rules League", commissioner_id=commissioner_id,
                        visibility=visibility, league_type=league_type, max_teams=max_teams,
                        co_commissioner_ids=co_commissioner_ids or [], scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


async def _add_teams(f, league_id, n, owner_id=None):
    async with f() as db:
        for i in range(n):
            db.add(Team(id=str(uuid.uuid4()), name=f"T{i}", league_id=league_id,
                        owner_id=owner_id, is_cpu=owner_id is None, roster=[]))
        await db.commit()


async def _invite(f, league_id, user_id, status=InviteStatus.ACCEPTED):
    async with f() as db:
        db.add(LeagueInvite(league_id=league_id, invited_email="x@test.local",
                            token_hash=uuid.uuid4().hex, status=status,
                            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                            accepted_by_user_id=user_id if status == InviteStatus.ACCEPTED else None))
        await db.commit()


async def _join_request(f, league_id, user_id, status):
    async with f() as db:
        db.add(LeagueJoinRequest(league_id=league_id, requested_by_user_id=user_id, status=status))
        await db.commit()


async def _team_count(f, league_id):
    async with f() as db:
        return await db.scalar(select(func.count(Team.id)).where(Team.league_id == league_id))


async def _create(client, token, league_id, **extra):
    return await client.post("/teams", json={"name": "New Team", "league_id": league_id, **extra},
                             headers={"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", [LeagueVisibility.PRIVATE, LeagueVisibility.INVITE_ONLY])
async def test_stranger_cannot_create_team(client, db_session_factory, visibility):
    commish, _ = await _make_user(db_session_factory)
    _stranger, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, visibility)

    r = await _create(client, token, league_id)
    assert r.status_code == 403
    assert await _team_count(db_session_factory, league_id) == 0

    # And creating a team didn't open up the league's reads either.
    if visibility == LeagueVisibility.PRIVATE:
        r = await client.get(f"/leagues/{league_id}/standings", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", [LeagueVisibility.PRIVATE, LeagueVisibility.INVITE_ONLY])
async def test_pending_or_revoked_access_is_not_enough(client, db_session_factory, visibility):
    commish, _ = await _make_user(db_session_factory)
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, visibility)
    await _invite(db_session_factory, league_id, user.id, status=InviteStatus.REVOKED)
    await _join_request(db_session_factory, league_id, user.id, JoinRequestStatus.PENDING)
    await _join_request(db_session_factory, league_id, user.id, JoinRequestStatus.DENIED)

    r = await _create(client, token, league_id)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_guest_gets_401(client, db_session_factory):
    commish, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, LeagueVisibility.PRIVATE)
    r = await client.post("/teams", json={"name": "x", "league_id": league_id})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unknown_league_is_404(client, db_session_factory):
    _user, token = await _make_user(db_session_factory)
    r = await _create(client, token, str(uuid.uuid4()))
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", [LeagueVisibility.PRIVATE, LeagueVisibility.INVITE_ONLY])
async def test_invited_user_can_create_team(client, db_session_factory, visibility):
    commish, _ = await _make_user(db_session_factory)
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, visibility)
    await _invite(db_session_factory, league_id, user.id)

    r = await _create(client, token, league_id)
    assert r.status_code == 201, r.text
    assert r.json()["owner_id"] == user.id
    assert r.json()["co_owner_id"] is None


@pytest.mark.asyncio
async def test_approved_join_request_can_create_team(client, db_session_factory):
    commish, _ = await _make_user(db_session_factory)
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, LeagueVisibility.INVITE_ONLY)
    await _join_request(db_session_factory, league_id, user.id, JoinRequestStatus.APPROVED)

    r = await _create(client, token, league_id)
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", list(LeagueVisibility))
async def test_commissioner_and_co_commissioner_can_create_team(client, db_session_factory, visibility):
    commish, commish_token = await _make_user(db_session_factory)
    co, co_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, visibility, co_commissioner_ids=[co.id])

    assert (await _create(client, commish_token, league_id)).status_code == 201
    assert (await _create(client, co_token, league_id)).status_code == 201


@pytest.mark.asyncio
async def test_open_league_still_open_to_anyone(client, db_session_factory):
    commish, _ = await _make_user(db_session_factory)
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, LeagueVisibility.OPEN)

    r = await _create(client, token, league_id)
    assert r.status_code == 201, r.text
    assert r.json()["owner_id"] == user.id


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", list(LeagueVisibility))
async def test_full_league_returns_400(client, db_session_factory, visibility):
    commish, commish_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, visibility, max_teams=4)
    await _add_teams(db_session_factory, league_id, 3)

    r = await _create(client, commish_token, league_id)
    assert r.status_code == 201, r.text  # the last open slot
    r = await _create(client, commish_token, league_id)
    assert r.status_code == 400
    assert r.json()["detail"] == "League is full"
    assert await _team_count(db_session_factory, league_id) == 4


@pytest.mark.asyncio
async def test_co_owner_id_is_rejected_on_create(client, db_session_factory):
    commish, commish_token = await _make_user(db_session_factory)
    other, _ = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, commish.id, LeagueVisibility.OPEN,
                                   league_type=LeagueType.TWO_MAN)

    r = await _create(client, commish_token, league_id, co_owner_id=other.id)
    assert r.status_code == 422
    assert await _team_count(db_session_factory, league_id) == 0


@pytest.mark.asyncio
async def test_create_league_then_team_then_cpu_fill_flow(client, db_session_factory):
    """The frontend's league-create flow: POST /leagues, POST /teams for
    the commissioner's own team, then bulk-add CPU teams for the rest."""
    _commish, token = await _make_user(db_session_factory)
    headers = {"Authorization": f"Bearer {token}"}
    for visibility in ("open", "invite_only", "private"):
        r = await client.post("/leagues", json={"name": f"L {visibility}", "visibility": visibility, "max_teams": 4},
                              headers=headers)
        assert r.status_code == 201, r.text
        league_id = r.json()["id"]

        r = await client.post("/teams", json={"name": "Mine", "league_id": league_id}, headers=headers)
        assert r.status_code == 201, r.text

        r = await client.post(f"/teams/bulk-add/{league_id}", json={"count": 3}, headers=headers)
        assert r.status_code == 201, r.text
        assert r.json()["total_teams"] == 4

        r = await client.post("/teams", json={"name": "Extra", "league_id": league_id}, headers=headers)
        assert r.status_code == 400
        r = await client.post(f"/teams/bulk-add/{league_id}", json={"count": 1}, headers=headers)
        assert r.status_code == 400
