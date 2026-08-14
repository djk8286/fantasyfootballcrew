"""
Tests for JWT revocation on password change/reset (User.token_version).
A token issued before the account's most recent password change/reset
must stop working immediately -- closing the "a stolen 30-day token
survives a password change" gap.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from app.models.user import User
from app.models.password_reset_token import PasswordResetToken
from app.services.auth_service import hash_password, hash_token, create_access_token


async def _make_user(db_session_factory, password="realpassword123"):
    async with db_session_factory() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=f"{uuid.uuid4()}@test.local",
            username=f"user{uuid.uuid4().hex[:8]}",
            hashed_password=hash_password(password),
            provider="email",
        )
        db.add(user)
        await db.commit()
        return user


@pytest.mark.asyncio
async def test_token_issued_before_password_change_401s_after_change(client, db_session_factory):
    user = await _make_user(db_session_factory, password="oldpassword123")
    old_token = create_access_token({"sub": user.id, "email": user.email, "token_version": user.token_version})

    client.headers["Authorization"] = f"Bearer {old_token}"
    r = await client.post("/users/me/change-password", json={
        "current_password": "oldpassword123", "new_password": "newpassword456",
    })
    assert r.status_code == 200

    # The token that JUST authenticated the change-password call itself
    # is now stale -- confirms token_version was actually bumped and is
    # actually enforced, not just written and ignored.
    r = await client.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fresh_login_after_password_change_keeps_working(client, db_session_factory):
    user = await _make_user(db_session_factory, password="oldpassword123")
    old_token = create_access_token({"sub": user.id, "email": user.email, "token_version": user.token_version})

    client.headers["Authorization"] = f"Bearer {old_token}"
    await client.post("/users/me/change-password", json={
        "current_password": "oldpassword123", "new_password": "newpassword456",
    })

    r = await client.post("/auth/login", json={"email": user.email, "password": "newpassword456"})
    assert r.status_code == 200
    new_token = r.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {new_token}"
    r = await client.get("/auth/me")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_token_issued_before_password_reset_401s_after_reset(client, db_session_factory):
    user = await _make_user(db_session_factory, password="oldpassword123")
    old_token = create_access_token({"sub": user.id, "email": user.email, "token_version": user.token_version})

    raw_token = "test-reset-token-abc123"
    async with db_session_factory() as db:
        db.add(PasswordResetToken(
            user_id=user.id, token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await db.commit()

    r = await client.post("/auth/reset-password", json={"token": raw_token, "new_password": "newpassword456"})
    assert r.status_code == 200

    client.headers["Authorization"] = f"Bearer {old_token}"
    r = await client.get("/auth/me")
    assert r.status_code == 401

    # A fresh login with the new password still works.
    client.headers.pop("Authorization", None)
    r = await client.post("/auth/login", json={"email": user.email, "password": "newpassword456"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_a_token_with_no_token_version_claim_still_works_for_an_unchanged_account(client, db_session_factory):
    """Backward compatibility: a token issued before this check existed
    (no token_version claim at all) must keep working for an account
    that hasn't changed its password since -- User.token_version
    defaults to 0, and payload.get("token_version", 0) defaults to 0
    too, so they line up without anyone needing to re-login."""
    user = await _make_user(db_session_factory)
    old_style_token = create_access_token({"sub": user.id, "email": user.email})  # no token_version claim

    client.headers["Authorization"] = f"Bearer {old_style_token}"
    r = await client.get("/auth/me")
    assert r.status_code == 200
