"""
Tests for claim-gating (Phase 1 Step 6) -- claim_team and claim_co_owner
actually enforcing League.visibility, not just the discovery listing
filter Step 2 added. Before this, an INVITE_ONLY or PRIVATE league's
teams could be claimed by literally anyone with the team_id, invite or
not.
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
        league = League(id=str(uuid.uuid4()), name="Claim Gating Test League", commissioner_id=commissioner_id,
                         visibility=visibility, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


async def _make_cpu_team(db_session_factory, league_id):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name="CPU Team", league_id=league_id, is_cpu=True, roster=[])
        db.add(team)
        await db.commit()
        return team.id


async def _make_claimed_team(db_session_factory, league_id, owner_id):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name="Claimed Team", league_id=league_id, owner_id=owner_id, is_cpu=False, roster=[])
        db.add(team)
        await db.commit()
        return team.id


async def _grant_accepted_invite(db_session_factory, league_id, inviter_id, accepted_by_user_id):
    async with db_session_factory() as db:
        invite = LeagueInvite(
            id=str(uuid.uuid4()), league_id=league_id, invited_email="whoever@test.local",
            invited_by_user_id=inviter_id, token_hash=f"unused-{uuid.uuid4()}",
            status=InviteStatus.ACCEPTED, expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            accepted_at=datetime.now(timezone.utc), accepted_by_user_id=accepted_by_user_id,
        )
        db.add(invite)
        await db.commit()


async def _grant_approved_join_request(db_session_factory, league_id, requester_id):
    async with db_session_factory() as db:
        jr = LeagueJoinRequest(
            id=str(uuid.uuid4()), league_id=league_id, requested_by_user_id=requester_id,
            status=JoinRequestStatus.APPROVED,
        )
        db.add(jr)
        await db.commit()


@pytest.mark.asyncio
async def test_claim_team_allowed_on_open_league(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)
    team_id = await _make_cpu_team(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post(f"/teams/{team_id}/claim")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_claim_team_blocked_on_invite_only_without_access(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    team_id = await _make_cpu_team(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post(f"/teams/{team_id}/claim")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_claim_team_blocked_on_private_league(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.PRIVATE)
    team_id = await _make_cpu_team(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post(f"/teams/{team_id}/claim")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_claim_team_allowed_with_accepted_invite(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    invitee, invitee_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    team_id = await _make_cpu_team(db_session_factory, league_id)
    await _grant_accepted_invite(db_session_factory, league_id, owner.id, invitee.id)

    client.headers["Authorization"] = f"Bearer {invitee_token}"
    r = await client.post(f"/teams/{team_id}/claim")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_claim_team_allowed_with_approved_join_request(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    requester, requester_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    team_id = await _make_cpu_team(db_session_factory, league_id)
    await _grant_approved_join_request(db_session_factory, league_id, requester.id)

    client.headers["Authorization"] = f"Bearer {requester_token}"
    r = await client.post(f"/teams/{team_id}/claim")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_claim_team_allowed_for_commissioner_regardless_of_visibility(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.PRIVATE)
    team_id = await _make_cpu_team(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r = await client.post(f"/teams/{team_id}/claim")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_claim_co_owner_blocked_on_invite_only_without_access(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    team_owner, _team_owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    team_id = await _make_claimed_team(db_session_factory, league_id, team_owner.id)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post(f"/teams/{team_id}/claim-co-owner")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_claim_co_owner_allowed_with_accepted_invite(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    team_owner, _team_owner_token = await _make_user(db_session_factory)
    invitee, invitee_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.INVITE_ONLY)
    team_id = await _make_claimed_team(db_session_factory, league_id, team_owner.id)
    await _grant_accepted_invite(db_session_factory, league_id, owner.id, invitee.id)

    client.headers["Authorization"] = f"Bearer {invitee_token}"
    r = await client.post(f"/teams/{team_id}/claim-co-owner")
    assert r.status_code == 200


# ─── Guillotine (Phase 4) -- eliminated-team gates ──────────────────────

async def _eliminate_team(db_session_factory, team_id, week=1):
    from sqlalchemy import select as _select
    async with db_session_factory() as db:
        result = await db.execute(_select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.eliminated_week = week
        await db.commit()


@pytest.mark.asyncio
async def test_claim_co_owner_blocked_on_eliminated_team(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    team_owner, _team_owner_token = await _make_user(db_session_factory)
    joiner, joiner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)
    team_id = await _make_claimed_team(db_session_factory, league_id, team_owner.id)
    await _eliminate_team(db_session_factory, team_id)

    client.headers["Authorization"] = f"Bearer {joiner_token}"
    r = await client.post(f"/teams/{team_id}/claim-co-owner")
    assert r.status_code == 400
    assert "eliminated" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_eliminated_teams_owner_can_join_a_survivor_team_in_same_league(client, db_session_factory):
    """The "join a survivor's team" mechanic: an eliminated manager
    already owns team A (now dead) in league L; nothing should stop them
    from claiming the open co-owner slot on a still-alive team B in that
    same league -- confirmed there's no "already in this league"
    restriction on claim_co_owner today."""
    owner, _owner_token = await _make_user(db_session_factory)
    eliminated_owner, eliminated_owner_token = await _make_user(db_session_factory)
    survivor_owner, _survivor_owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)
    dead_team_id = await _make_claimed_team(db_session_factory, league_id, eliminated_owner.id)
    await _eliminate_team(db_session_factory, dead_team_id)
    survivor_team_id = await _make_claimed_team(db_session_factory, league_id, survivor_owner.id)

    client.headers["Authorization"] = f"Bearer {eliminated_owner_token}"
    r = await client.post(f"/teams/{survivor_team_id}/claim-co-owner")
    assert r.status_code == 200
    assert r.json()["co_owner_id"] == eliminated_owner.id


@pytest.mark.asyncio
async def test_last_words_rejected_on_a_non_eliminated_team(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)
    team_id = await _make_claimed_team(db_session_factory, league_id, owner.id)

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r = await client.patch(f"/teams/{team_id}", json={"last_words": "gg"})
    assert r.status_code == 400
    assert "eliminated" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_last_words_accepted_and_persisted_on_an_eliminated_team(client, db_session_factory):
    owner, owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)
    team_id = await _make_claimed_team(db_session_factory, league_id, owner.id)
    await _eliminate_team(db_session_factory, team_id)

    client.headers["Authorization"] = f"Bearer {owner_token}"
    r = await client.patch(f"/teams/{team_id}", json={"last_words": "gg no re"})
    assert r.status_code == 200
    assert r.json()["last_words"] == "gg no re"


@pytest.mark.asyncio
async def test_last_words_forbidden_for_a_stranger(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    team_owner, _team_owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id, LeagueVisibility.OPEN)
    team_id = await _make_claimed_team(db_session_factory, league_id, team_owner.id)
    await _eliminate_team(db_session_factory, team_id)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.patch(f"/teams/{team_id}", json={"last_words": "should not land"})
    assert r.status_code == 403
