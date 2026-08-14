"""
Tests for track-only email verification (Auth Security Hardening,
Step 3) -- registering sends a verification email and creates a
single-use token, but nothing is gated on it being clicked. Explicitly
regression-pins the "track-only" behavior so a future change doesn't
accidentally start blocking unverified accounts without a deliberate
decision to do so.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select, func
from app.models.user import User
from app.models.email_verification_token import EmailVerificationToken
from app.services.auth_service import hash_token
import app.api.v1.auth as auth_module


@pytest.mark.asyncio
async def test_register_creates_exactly_one_verification_token_and_sends_email(client, monkeypatch):
    captured = {}

    async def spy(to_email, verify_link):
        captured["to_email"] = to_email
        captured["verify_link"] = verify_link

    monkeypatch.setattr(auth_module, "send_verification_email", spy)

    email = f"{uuid.uuid4()}@example.com"
    r = await client.post("/auth/register", json={
        "email": email, "username": f"user{uuid.uuid4().hex[:8]}", "password": "password123",
    })
    assert r.status_code == 200

    assert captured["to_email"] == email
    assert "/verify-email?token=" in captured["verify_link"]


@pytest.mark.asyncio
async def test_verify_email_flips_the_flag_on_a_valid_token(client, db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"user{uuid.uuid4().hex[:8]}", hashed_password=None, provider="google")
        db.add(user)
        await db.flush()
        raw_token = "test-verify-token-xyz"
        db.add(EmailVerificationToken(
            user_id=user.id, token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        ))
        await db.commit()
        user_id = user.id

    assert (await _is_verified(db_session_factory, user_id)) is False

    r = await client.post("/auth/verify-email", json={"token": raw_token})
    assert r.status_code == 200
    assert (await _is_verified(db_session_factory, user_id)) is True


@pytest.mark.asyncio
async def test_verify_email_rejects_bogus_token(client):
    r = await client.post("/auth/verify-email", json={"token": "totally-made-up"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_verify_email_rejects_expired_token(client, db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"user{uuid.uuid4().hex[:8]}", hashed_password=None, provider="google")
        db.add(user)
        await db.flush()
        raw_token = "expired-token-abc"
        db.add(EmailVerificationToken(
            user_id=user.id, token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        await db.commit()
        user_id = user.id

    r = await client.post("/auth/verify-email", json={"token": raw_token})
    assert r.status_code == 400
    assert (await _is_verified(db_session_factory, user_id)) is False


@pytest.mark.asyncio
async def test_verify_email_rejects_already_used_token(client, db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"user{uuid.uuid4().hex[:8]}", hashed_password=None, provider="google")
        db.add(user)
        await db.flush()
        raw_token = "already-used-token"
        db.add(EmailVerificationToken(
            user_id=user.id, token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
            used_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    r = await client.post("/auth/verify-email", json={"token": raw_token})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_registering_and_never_verifying_still_allows_full_normal_use(client, monkeypatch):
    """Regression pin for "track-only, not enforced" -- registering,
    logging in, and using an authenticated endpoint must all work with
    zero interaction with the verification link."""
    async def spy(to_email, verify_link):
        pass
    monkeypatch.setattr(auth_module, "send_verification_email", spy)

    email = f"{uuid.uuid4()}@example.com"
    r = await client.post("/auth/register", json={
        "email": email, "username": f"user{uuid.uuid4().hex[:8]}", "password": "password123",
    })
    assert r.status_code == 200

    r = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == email


@pytest.mark.asyncio
async def test_register_rejects_malformed_email(client):
    r = await client.post("/auth/register", json={
        "email": "not-an-email", "username": f"user{uuid.uuid4().hex[:8]}", "password": "password123",
    })
    assert r.status_code == 422


async def _is_verified(db_session_factory, user_id: str) -> bool:
    async with db_session_factory() as db:
        return (await db.execute(select(User).where(User.id == user_id))).scalar_one().email_verified
