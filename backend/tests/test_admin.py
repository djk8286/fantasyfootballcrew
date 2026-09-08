"""
Tests for the read-only admin dashboard (app/api/v1/admin.py) -- gated
entirely on User.is_admin, not on being a specific hardcoded account.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League
from app.models.team import Team
from app.services.auth_service import hash_password, create_access_token


async def _make_user(db_session_factory, is_admin: bool = False):
    async with db_session_factory() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=f"{uuid.uuid4()}@test.local",
            username=f"user{uuid.uuid4().hex[:8]}",
            hashed_password=hash_password("realpassword123"),
            is_admin=is_admin,
        )
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email, "token_version": 0})
        return user, token


@pytest.mark.asyncio
async def test_non_admin_gets_403_on_every_admin_route(client, db_session_factory):
    _user, token = await _make_user(db_session_factory, is_admin=False)
    client.headers["Authorization"] = f"Bearer {token}"

    for path in ["/admin/stats", "/admin/users", "/admin/leagues"]:
        r = await client.get(path)
        assert r.status_code == 403, path


@pytest.mark.asyncio
async def test_logged_out_gets_401_on_admin_routes(client):
    client.headers.pop("Authorization", None)
    r = await client.get("/admin/stats")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_can_see_stats_and_users(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    other, _ = await _make_user(db_session_factory, is_admin=False)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.get("/admin/stats")
    assert r.status_code == 200
    assert r.json()["users"] >= 2

    r = await client.get("/admin/users")
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()}
    assert admin.username in usernames
    assert other.username in usernames
    # Email IS included here -- this is the admin-only view, distinct
    # from GET /users/{id}'s public (no-email) UserPublic response.
    admin_row = next(u for u in r.json() if u["id"] == admin.id)
    assert admin_row["email"] == admin.email
    assert admin_row["is_admin"] is True


@pytest.mark.asyncio
async def test_admin_leagues_list_includes_commissioner_and_team_count(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(
            id=str(uuid.uuid4()), name="Admin View Test League", commissioner_id=commissioner.id,
            scoring_config={}, roster_slots={},
        )
        db.add(league)
        await db.flush()
        db.add(Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id, is_cpu=True, roster=[]))
        db.add(Team(id=str(uuid.uuid4()), name="Team B", league_id=league.id, is_cpu=True, roster=[]))
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/leagues")
    assert r.status_code == 200
    row = next(l for l in r.json() if l["id"] == league_id)
    assert row["commissioner_username"] == commissioner.username
    assert row["commissioner_email"] == commissioner.email
    assert row["team_count"] == 2
