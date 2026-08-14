"""
Tests for the in-app user settings additions: PUT /users/me (username),
POST /users/me/change-password, and DELETE /users/me (self-service
account deletion, Production Quality Hardening Phase 2). Previously
there was no way for a logged-in user to change either password without
going through the DB directly, or to delete their own account at all --
only support/direct-DB access could.

DELETE /users/me shares change-password's 5/hour limit *shape* (its own
separate bucket, but same low tier) -- reset the limiter around every
test in this file so the two endpoints' tests don't pollute each other
or themselves across this many test functions. See test_rate_limits.py's
identical fixture/rationale.
"""
import uuid
import pytest
from app.core.limiter import limiter
from app.models.user import User
from app.models.league import League
from app.models.team import Team
from app.services.auth_service import hash_password, create_access_token


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


async def _make_user(db_session_factory, password="realpassword123", provider="email"):
    async with db_session_factory() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=f"{uuid.uuid4()}@test.local",
            username=f"user{uuid.uuid4().hex[:8]}",
            hashed_password=hash_password(password) if provider == "email" else None,
            provider=provider,
        )
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email, "token_version": 0})
        return user, token


@pytest.mark.asyncio
async def test_update_username(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.put("/users/me", json={"username": "brandnewname"})
    assert r.status_code == 200
    assert r.json()["username"] == "brandnewname"

    r = await client.get("/users/me")
    assert r.json()["username"] == "brandnewname"


@pytest.mark.asyncio
async def test_cannot_take_an_already_used_username(client, db_session_factory):
    existing_user, _token1 = await _make_user(db_session_factory)
    _other_user, token2 = await _make_user(db_session_factory)

    client.headers["Authorization"] = f"Bearer {token2}"
    r = await client.put("/users/me", json={"username": existing_user.username})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_updating_to_your_own_current_username_is_a_noop_success(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put("/users/me", json={"username": user.username})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_change_password_with_correct_current_password(client, db_session_factory):
    user, token = await _make_user(db_session_factory, password="oldpassword123")
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/users/me/change-password", json={
        "current_password": "oldpassword123", "new_password": "newpassword456",
    })
    assert r.status_code == 200

    # New password now actually logs in; old one no longer works.
    r = await client.post("/auth/login", json={"email": user.email, "password": "newpassword456"})
    assert r.status_code == 200
    r = await client.post("/auth/login", json={"email": user.email, "password": "oldpassword123"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password(client, db_session_factory):
    user, token = await _make_user(db_session_factory, password="oldpassword123")
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/users/me/change-password", json={
        "current_password": "totallywrong", "new_password": "newpassword456",
    })
    assert r.status_code == 401

    # Old password still works -- nothing changed.
    r = await client.post("/auth/login", json={"email": user.email, "password": "oldpassword123"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_change_password_rejects_too_short_new_password(client, db_session_factory):
    _user, token = await _make_user(db_session_factory, password="oldpassword123")
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/users/me/change-password", json={
        "current_password": "oldpassword123", "new_password": "short",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_change_password_rejects_google_only_account(client, db_session_factory):
    """provider=google, hashed_password=None -- no password to verify
    against or change, and shouldn't pretend there is one."""
    _user, token = await _make_user(db_session_factory, provider="google")
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/users/me/change-password", json={
        "current_password": "anything", "new_password": "newpassword456",
    })
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_settings_endpoints_require_auth(client):
    client.headers.pop("Authorization", None)
    r = await client.put("/users/me", json={"username": "whatever"})
    assert r.status_code in (401, 403)
    r = await client.post("/users/me/change-password", json={"current_password": "a", "new_password": "bbbbbbbb"})
    assert r.status_code in (401, 403)


# ─── DELETE /users/me (self-service account deletion) ──────────────────

async def _make_league_with_teams(db_session_factory, commissioner_id, other_owners=()):
    """A league commissioned by `commissioner_id`, with one team per id in
    `other_owners` (real, non-CPU) plus one CPU team, so tests can control
    exactly whether a "successor" commissioner exists."""
    async with db_session_factory() as db:
        league = League(
            id=str(uuid.uuid4()), name="Delete-Account Test League", commissioner_id=commissioner_id,
            scoring_config={}, roster_slots={},
        )
        db.add(league)
        await db.flush()
        db.add(Team(id=str(uuid.uuid4()), name="Commissioner's Team", league_id=league.id,
                     owner_id=commissioner_id, is_cpu=False, roster=[]))
        for uid in other_owners:
            db.add(Team(id=str(uuid.uuid4()), name=f"Team {uid[:6]}", league_id=league.id,
                        owner_id=uid, is_cpu=False, roster=[]))
        db.add(Team(id=str(uuid.uuid4()), name="CPU Filler", league_id=league.id,
                    owner_id=None, is_cpu=True, roster=[]))
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_delete_own_account_hard_deletes_and_revokes_session(client, db_session_factory):
    user, token = await _make_user(db_session_factory, password="realpassword123")
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={"password": "realpassword123"})
    assert r.status_code == 200

    # The now-deleted account's own token no longer authenticates anything.
    r = await client.get("/users/me")
    assert r.status_code == 401

    # And a fresh login attempt fails outright -- the row is really gone.
    r = await client.post("/auth/login", json={"email": user.email, "password": "realpassword123"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_account_rejects_wrong_password(client, db_session_factory):
    user, token = await _make_user(db_session_factory, password="realpassword123")
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={"password": "totallywrong"})
    # 400, not 401 -- see delete_me's own comment: this must not trip the
    # frontend's "401 with a token means the token is bad" auto-logout.
    assert r.status_code == 400

    # Nothing happened -- the account still logs in fine.
    r = await client.post("/auth/login", json={"email": user.email, "password": "realpassword123"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_google_oauth_account_needs_no_password(client, db_session_factory):
    _user, token = await _make_user(db_session_factory, provider="google")
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={})
    assert r.status_code == 200

    r = await client.get("/users/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_blocked_when_sole_real_member_of_a_league(client, db_session_factory):
    user, token = await _make_user(db_session_factory, password="realpassword123")
    await _make_league_with_teams(db_session_factory, commissioner_id=user.id)  # no other_owners
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={"password": "realpassword123"})
    assert r.status_code == 409

    # Nothing was persisted -- account still fully intact.
    r = await client.get("/users/me")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_delete_auto_transfers_commissioner_to_another_real_owner(client, db_session_factory):
    user, token = await _make_user(db_session_factory, password="realpassword123")
    successor, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner_id=user.id, other_owners=[successor.id])
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={"password": "realpassword123"})
    assert r.status_code == 200

    r = await client.get(f"/leagues/{league_id}")
    assert r.status_code == 200
    assert r.json()["commissioner_id"] == successor.id


@pytest.mark.asyncio
async def test_delete_nulls_team_ownership_and_flips_to_cpu(client, db_session_factory):
    """Deleting an account that owns a team elsewhere (not commissioning
    it) shouldn't be blocked at all -- the team just becomes CPU-owned,
    same shape bulk_add_cpu_teams already produces."""
    commissioner, _ = await _make_user(db_session_factory)
    user, token = await _make_user(db_session_factory, password="realpassword123")
    league_id = await _make_league_with_teams(db_session_factory, commissioner_id=commissioner.id, other_owners=[user.id])
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={"password": "realpassword123"})
    assert r.status_code == 200

    r = await client.get(f"/teams/league/{league_id}")
    assert r.status_code == 200
    teams = {t["name"]: t for t in r.json()}
    flipped = teams[f"Team {user.id[:6]}"]
    assert flipped["owner_id"] is None
    assert flipped["is_cpu"] is True

    # League untouched -- still commissioned by the same person as before.
    r = await client.get(f"/leagues/{league_id}")
    assert r.json()["commissioner_id"] == commissioner.id
