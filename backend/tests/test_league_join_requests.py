"""
Tests for LeagueJoinRequest -- the "or approval" half of Invite-only
leagues: a user who found the league through discovery asks the
commissioner for access, as opposed to LeagueInvite where the
commissioner reaches out first. See radiant-booping-eagle plan,
Phase 1 Step 5.
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


async def _make_league(db_session_factory, commissioner_id, visibility=LeagueVisibility.INVITE_ONLY):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Join Request Test League", commissioner_id=commissioner_id,
                         visibility=visibility, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_create_join_request_on_invite_only_league(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r = await client.post(f"/leagues/{league_id}/join-requests", json={"message": "Let me in!"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["message"] == "Let me in!"
    assert body["requester_username"] == requester.username


@pytest.mark.asyncio
async def test_join_request_rejected_for_open_league(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, visibility=LeagueVisibility.OPEN)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r = await client.post(f"/leagues/{league_id}/join-requests", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_join_request_rejected_for_private_league(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, visibility=LeagueVisibility.PRIVATE)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r = await client.post(f"/leagues/{league_id}/join-requests", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_pending_request_rejected(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r1 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    assert r1.status_code == 201
    r2 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_resubmit_allowed_after_denial(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r1 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    request_id = r1.json()["id"]

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r2 = await client.post(f"/leagues/{league_id}/join-requests/{request_id}/decision", json={"action": "deny"})
    assert r2.status_code == 200
    assert r2.json()["decision"] == "denied"

    # A fresh request should now be allowed, since the prior one is no
    # longer PENDING.
    client.headers["Authorization"] = f"Bearer {requester_token}"
    r3 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    assert r3.status_code == 201


@pytest.mark.asyncio
async def test_non_commissioner_cannot_list_join_requests(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.get(f"/leagues/{league_id}/join-requests")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_commissioner_lists_join_requests(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    await client.post(f"/leagues/{league_id}/join-requests", json={"message": "please"})

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r = await client.get(f"/leagues/{league_id}/join-requests")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["requester_username"] == requester.username


@pytest.mark.asyncio
async def test_commissioner_approves_join_request(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r1 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    request_id = r1.json()["id"]

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r2 = await client.post(f"/leagues/{league_id}/join-requests/{request_id}/decision", json={"action": "approve"})
    assert r2.status_code == 200
    assert r2.json()["decision"] == "approved"

    r3 = await client.get(f"/leagues/{league_id}/join-requests")
    assert r3.json()[0]["status"] == "approved"


@pytest.mark.asyncio
async def test_non_commissioner_cannot_decide_join_request(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r1 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    request_id = r1.json()["id"]

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r2 = await client.post(f"/leagues/{league_id}/join-requests/{request_id}/decision", json={"action": "approve"})
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_already_decided_request_cannot_be_decided_again(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r1 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    request_id = r1.json()["id"]

    client.headers["Authorization"] = f"Bearer {owner_token}"
    await client.post(f"/leagues/{league_id}/join-requests/{request_id}/decision", json={"action": "approve"})
    r2 = await client.post(f"/leagues/{league_id}/join-requests/{request_id}/decision", json={"action": "deny"})
    assert r2.status_code == 400
