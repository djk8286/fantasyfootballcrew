"""
Tests for commissioner email invites (LeagueInvite) -- the token-based
join mechanism for Invite-only/Private leagues. See radiant-booping-eagle
plan, Phase 1 Step 4.
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from app.models.user import User
from app.models.league import League, LeagueVisibility
from app.models.league_invite import LeagueInvite, InviteStatus
from app.models.team import Team
from app.services.auth_service import create_access_token, hash_token


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, name="Invite Test League", visibility=LeagueVisibility.INVITE_ONLY):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name=name, commissioner_id=commissioner_id,
                         visibility=visibility, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_commissioner_can_send_invites(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post(f"/leagues/{league_id}/invites", json={"emails": ["friend@test.local"], "message": "Join us!"})
    assert r.status_code == 201
    body = r.json()
    assert len(body) == 1
    assert body[0]["invited_email"] == "friend@test.local"
    assert body[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_non_commissioner_cannot_send_invites(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/leagues/{league_id}/invites", json={"emails": ["friend@test.local"]})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_too_many_emails_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post(f"/leagues/{league_id}/invites", json={"emails": [f"e{i}@test.local" for i in range(21)]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_invites_shows_commissioners_own_league(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    client.headers["Authorization"] = f"Bearer {token}"
    await client.post(f"/leagues/{league_id}/invites", json={"emails": ["a@test.local", "b@test.local"]})

    r = await client.get(f"/leagues/{league_id}/invites")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_revoke_pending_invite(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post(f"/leagues/{league_id}/invites", json={"emails": ["a@test.local"]})
    invite_id = r.json()[0]["id"]

    r = await client.delete(f"/leagues/{league_id}/invites/{invite_id}")
    assert r.status_code == 200

    r = await client.get(f"/leagues/{league_id}/invites")
    assert r.json()[0]["status"] == "revoked"


async def _make_raw_invite(db_session_factory, league_id, inviter_id, email="invitee@test.local",
                            status=InviteStatus.PENDING, expires_delta=timedelta(days=14)):
    raw_token = f"rawtoken-{uuid.uuid4()}"
    async with db_session_factory() as db:
        invite = LeagueInvite(
            id=str(uuid.uuid4()), league_id=league_id, invited_email=email,
            invited_by_user_id=inviter_id, token_hash=hash_token(raw_token),
            status=status, expires_at=datetime.now(timezone.utc) + expires_delta,
        )
        db.add(invite)
        await db.commit()
    return raw_token


@pytest.mark.asyncio
async def test_get_invite_landing_page_public_no_auth(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id)

    client.headers.pop("Authorization", None)
    r = await client.get(f"/invites/{raw_token}")
    assert r.status_code == 200
    body = r.json()
    assert body["league_id"] == league_id
    assert body["usable"] is True


@pytest.mark.asyncio
async def test_accept_invite_requires_auth(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id)

    client.headers.pop("Authorization", None)
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_accept_invite_marks_accepted(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id)
    _acceptor, acceptor_token = await _make_user(db_session_factory)

    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 200
    assert r.json()["league_id"] == league_id

    # Now the landing page reports it as no longer usable.
    client.headers.pop("Authorization", None)
    r = await client.get(f"/invites/{raw_token}")
    assert r.json()["usable"] is False


@pytest.mark.asyncio
async def test_accept_invite_is_token_possession_based_not_email_matching(client, db_session_factory):
    """A different account than invited_email can still accept -- the
    token itself is the authorization, same trust model as password
    reset. See LeagueInvite's docstring."""
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id, email="someone-else@test.local")
    _acceptor, acceptor_token = await _make_user(db_session_factory)

    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_expired_invite_cannot_be_accepted(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id, expires_delta=timedelta(days=-1))
    _acceptor, acceptor_token = await _make_user(db_session_factory)

    client.headers.pop("Authorization", None)
    r = await client.get(f"/invites/{raw_token}")
    assert r.json()["usable"] is False

    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_already_accepted_invite_cannot_be_accepted_again(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id, status=InviteStatus.ACCEPTED)
    _acceptor, acceptor_token = await _make_user(db_session_factory)

    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unknown_token_404s(client, db_session_factory):
    client.headers.pop("Authorization", None)
    r = await client.get("/invites/not-a-real-token")
    assert r.status_code == 404


# ─── Auto-claim on accept ────────────────────────────────────────────
# Accepting used to be a dead end -- "in" the league but owning nothing,
# with claiming a team left as a separate, easy-to-miss step. Accepting
# now auto-claims the first open CPU team, same rename-on-claim behavior
# claim_team itself has.

async def _add_cpu_team(db_session_factory, league_id, name="CPU Team 1"):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name=name, league_id=league_id, is_cpu=True, roster=[])
        db.add(team)
        await db.commit()
        return team.id


@pytest.mark.asyncio
async def test_accept_invite_auto_claims_an_open_team(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    await _add_cpu_team(db_session_factory, league_id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id)
    acceptor, acceptor_token = await _make_user(db_session_factory)

    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 200
    body = r.json()
    assert body["claimed_team_id"] is not None
    assert body["claimed_team_name"] == f"{acceptor.username}'s Team"

    r = await client.get(f"/teams/{body['claimed_team_id']}")
    assert r.json()["owner_id"] == acceptor.id
    assert r.json()["is_cpu"] is False


@pytest.mark.asyncio
async def test_accept_invite_with_no_open_teams_still_succeeds(client, db_session_factory):
    """No CPU team available (e.g. league already full of real owners)
    -- accepting must still succeed, just without a claimed_team_id.
    The manual claim UI stays as a fallback."""
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id)
    _acceptor, acceptor_token = await _make_user(db_session_factory)

    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 200
    assert "claimed_team_id" not in r.json()


@pytest.mark.asyncio
async def test_accept_invite_does_not_reclaim_if_already_own_a_team(client, db_session_factory):
    """Re-clicking an old invite link after already having a team in
    this league must not reassign/rename it."""
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)
    await _add_cpu_team(db_session_factory, league_id, name="CPU Team 1")
    acceptor, acceptor_token = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        existing_team = Team(id=str(uuid.uuid4()), name="Already Mine", league_id=league_id,
                              owner_id=acceptor.id, is_cpu=False, roster=[])
        db.add(existing_team)
        await db.commit()

    raw_token = await _make_raw_invite(db_session_factory, league_id, user.id)
    client.headers["Authorization"] = f"Bearer {acceptor_token}"
    r = await client.post(f"/invites/{raw_token}/accept")
    assert r.status_code == 200
    assert "claimed_team_id" not in r.json()

    r = await client.get(f"/teams/league/{league_id}")
    names = {t["name"] for t in r.json()}
    assert "Already Mine" in names
    assert "CPU Team 1" in names  # untouched, still CPU
