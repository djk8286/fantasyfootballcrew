"""
Tests for real password hashing (bcrypt, replacing a previous plain
salted-SHA-256 implementation whose own docstring falsely claimed
bcrypt was already in use) and the transparent lazy-migration path for
existing accounts still on the legacy format.
"""
import hashlib
import secrets
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.services.auth_service import hash_password, verify_password, needs_rehash


def _legacy_hash(password: str) -> str:
    """Hand-construct a hash in the OLD format (salt:sha256hash) --
    exactly what auth_service.hash_password used to produce, before
    this pass switched it to bcrypt. Used to simulate an existing
    account that hasn't logged in since the migration yet."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{pwd_hash}"


def test_new_passwords_hash_to_bcrypt_format():
    hashed = hash_password("correcthorsebattery")
    assert hashed.startswith("$2")
    assert not needs_rehash(hashed)


def test_needs_rehash_identifies_each_format_correctly():
    assert needs_rehash(_legacy_hash("whatever")) is True
    assert needs_rehash(hash_password("whatever")) is False


def test_verify_password_works_against_a_fresh_bcrypt_hash():
    hashed = hash_password("correcthorsebattery")
    assert verify_password("correcthorsebattery", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_verify_password_still_works_against_a_legacy_hash():
    legacy = _legacy_hash("correcthorsebattery")
    assert verify_password("correcthorsebattery", legacy) is True
    assert verify_password("wrongpassword", legacy) is False


def test_verify_password_never_raises_on_garbage_input():
    assert verify_password("anything", "not-a-real-hash-at-all") is False
    assert verify_password("anything", "") is False


async def _make_legacy_user(db_session_factory, password="oldpassword123"):
    async with db_session_factory() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=f"{uuid.uuid4()}@test.local",
            username=f"legacyuser{uuid.uuid4().hex[:8]}",
            hashed_password=_legacy_hash(password),
            provider="email",
        )
        db.add(user)
        await db.commit()
        return user.id


@pytest.mark.asyncio
async def test_login_transparently_upgrades_a_legacy_hash_to_bcrypt(client, db_session_factory):
    user_id = await _make_legacy_user(db_session_factory, password="oldpassword123")

    async with db_session_factory() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        email = user.email
        assert needs_rehash(user.hashed_password) is True  # sanity check on the fixture itself

    r = await client.post("/auth/login", json={"email": email, "password": "oldpassword123"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        assert needs_rehash(user.hashed_password) is False  # now bcrypt

    # Second login with the same password still works -- proves the
    # rehashed value is actually correct, not just a format change.
    r = await client.post("/auth/login", json={"email": email, "password": "oldpassword123"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_with_wrong_password_never_rehashes_a_legacy_account(client, db_session_factory):
    user_id = await _make_legacy_user(db_session_factory, password="oldpassword123")

    r = await client.post("/auth/login", json={"email": (await _get_email(db_session_factory, user_id)), "password": "totallywrong"})
    assert r.status_code == 401

    async with db_session_factory() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        assert needs_rehash(user.hashed_password) is True  # unchanged -- still legacy format


async def _get_email(db_session_factory, user_id: str) -> str:
    async with db_session_factory() as db:
        return (await db.execute(select(User).where(User.id == user_id))).scalar_one().email
