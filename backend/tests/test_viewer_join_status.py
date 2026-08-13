"""
Tests for LeagueRead.viewer_join_status (Phase 1 Step 7) -- the "does
this viewer already have access" signal the league detail page's
claim-button region branches on.
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from app.models.user import User
from app.models.league import League, LeagueVisibility
from app.models.team import Team
from app.models.league_invite import LeagueInvite, InviteStatus
from app.models.league_join_request import LeagueJoinRequest, JoinRequestStatus
from app.services.auth_service import create_access_token


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, visibility):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Viewer Status Test League", commissioner_id=commissioner_id,
                         visibility=visibility, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_viewer_join_status_absent_when_logged_out(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)

    client.headers.pop("Authorization", None)
    r = await client.get(f"/leagues/{league_id}")
    assert r.status_code == 200
    assert r.json()["viewer_join_status"] is None


@pytest.mark.asyncio
async def test_viewer_join_status_commissioner(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.PRIVATE)

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["viewer_join_status"] == "commissioner"


@pytest.mark.asyncio
async def test_viewer_join_status_member(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    member, member_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name="My Team", league_id=league_id, owner_id=member.id, is_cpu=False, roster=[])
        db.add(team)
        await db.commit()

    client.headers["Authorization"] = f"Bearer {member_token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["viewer_join_status"] == "member"


@pytest.mark.asyncio
async def test_viewer_join_status_eligible_on_open_league(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["viewer_join_status"] == "eligible"


@pytest.mark.asyncio
async def test_viewer_join_status_blocked_on_invite_only(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["viewer_join_status"] == "blocked"


@pytest.mark.asyncio
async def test_viewer_join_status_requested(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    async with db_session_factory() as db:
        jr = LeagueJoinRequest(id=str(uuid.uuid4()), league_id=league_id, requested_by_user_id=requester.id,
                                status=JoinRequestStatus.PENDING)
        db.add(jr)
        await db.commit()

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["viewer_join_status"] == "requested"


@pytest.mark.asyncio
async def test_viewer_join_status_eligible_after_approval(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    async with db_session_factory() as db:
        jr = LeagueJoinRequest(id=str(uuid.uuid4()), league_id=league_id, requested_by_user_id=requester.id,
                                status=JoinRequestStatus.APPROVED)
        db.add(jr)
        await db.commit()

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["viewer_join_status"] == "eligible"


@pytest.mark.asyncio
async def test_viewer_join_status_invited_by_pending_email_match(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    invitee, invitee_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    async with db_session_factory() as db:
        invite = LeagueInvite(
            id=str(uuid.uuid4()), league_id=league_id, invited_email=invitee.email,
            invited_by_user_id=owner.id, token_hash=f"unused-{uuid.uuid4()}",
            status=InviteStatus.PENDING, expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db.add(invite)
        await db.commit()

    client.headers["Authorization"] = f"Bearer {invitee_token}"
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["viewer_join_status"] == "invited"
