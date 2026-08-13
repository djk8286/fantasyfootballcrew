"""
Tests for the notification wiring added in Phase 1 Step 10: an accepted
LeagueInvite notifies the specific inviter, a new LeagueJoinRequest
notifies every commissioner/co-commissioner, and a decided join request
notifies the requester.
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.models.league import League, LeagueVisibility
from app.models.league_invite import LeagueInvite, InviteStatus
from app.services.auth_service import create_access_token, hash_token


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, visibility=LeagueVisibility.INVITE_ONLY, co_commissioner_ids=None):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Notify Test League", commissioner_id=commissioner_id,
                         visibility=visibility, co_commissioner_ids=co_commissioner_ids or [],
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


async def _notifications_for(db_session_factory, user_id):
    async with db_session_factory() as db:
        result = await db.execute(select(Notification).where(Notification.user_id == user_id))
        return result.scalars().all()


@pytest.mark.asyncio
async def test_accepting_invite_notifies_the_inviter(client, db_session_factory):
    inviter, _inviter_token = await _make_user(db_session_factory)
    acceptor, acceptor_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, inviter.id)

    raw_token = f"rawtoken-{uuid.uuid4()}"
    async with db_session_factory() as db:
        invite = LeagueInvite(
            id=str(uuid.uuid4()), league_id=league_id, invited_email="whoever@test.local",
            invited_by_user_id=inviter.id, token_hash=hash_token(raw_token),
            status=InviteStatus.PENDING, expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.add(invite)
        await db.commit()

    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 200

    notifications = await _notifications_for(db_session_factory, inviter.id)
    assert len(notifications) == 1
    assert notifications[0].type == NotificationType.LEAGUE_INVITE_ACCEPTED
    assert acceptor.username in notifications[0].message


@pytest.mark.asyncio
async def test_join_request_notifies_all_commissioners(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    co_commish, _co_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, co_commissioner_ids=[co_commish.id])

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r = await client.post(f"/leagues/{league_id}/join-requests", json={})
    assert r.status_code == 201

    owner_notifications = await _notifications_for(db_session_factory, owner.id)
    co_notifications = await _notifications_for(db_session_factory, co_commish.id)
    assert len(owner_notifications) == 1
    assert owner_notifications[0].type == NotificationType.JOIN_REQUEST_RECEIVED
    assert len(co_notifications) == 1
    assert co_notifications[0].type == NotificationType.JOIN_REQUEST_RECEIVED
    assert requester.username in owner_notifications[0].message


@pytest.mark.asyncio
async def test_join_request_decision_notifies_requester(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r1 = await client.post(f"/leagues/{league_id}/join-requests", json={})
    request_id = r1.json()["id"]

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r2 = await client.post(f"/leagues/{league_id}/join-requests/{request_id}/decision", json={"action": "approve"})
    assert r2.status_code == 200

    notifications = await _notifications_for(db_session_factory, requester.id)
    decided = [n for n in notifications if n.type == NotificationType.JOIN_REQUEST_DECIDED]
    assert len(decided) == 1
    assert "approved" in decided[0].message
