"""
Tests for the in-app user settings additions: PUT /users/me (username)
and POST /users/me/change-password. Previously there was no way for a
logged-in user to change either without going through the DB directly --
only the email-link forgot/reset-password flow existed, for a password
you'd already forgotten, not one you still remember and just want to
change.
"""
import uuid
import pytest
from app.models.user import User
from app.services.auth_service import hash_password, create_access_token


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
        token = create_access_token({"sub": user.id, "email": user.email})
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
