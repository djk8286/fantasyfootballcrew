"""Cookie auth: HttpOnly access/refresh cookies, rotation, reuse detection,
logout, token_version revocation, CSRF origin check, legacy Bearer upgrade."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.limiter import limiter
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import hash_password, create_access_token

ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


async def _user(db_session_factory, pw="cookiepass123"):
    async with db_session_factory() as db:
        u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@test.local",
                 username=f"u{uuid.uuid4().hex[:8]}", hashed_password=hash_password(pw), provider="email")
        db.add(u)
        await db.commit()
        return u


async def _login(client, u, pw="cookiepass123"):
    r = await client.post("/auth/login", json={"email": u.email, "password": pw}, headers=ORIGIN)
    assert r.status_code == 200
    return r


def _set(client, name, value, path):
    """Replace a cookie in place (same domain as the server-set one) so the
    jar never holds two same-named cookies."""
    existing = _cookie(client, name)
    domain = existing.domain if existing is not None else "test.local"
    for c in list(client.cookies.jar):
        if c.name == name:
            client.cookies.jar.clear(c.domain, c.path, c.name)
    client.cookies.set(name, value, domain=domain, path=path)


def _cookie(client, name):
    for c in client.cookies.jar:
        if c.name == name:
            return c
    return None


@pytest.mark.asyncio
async def test_login_sets_httponly_cookies_and_me_works_without_bearer(client, db_session_factory):
    u = await _user(db_session_factory)
    r = await _login(client, u)
    set_cookie = r.headers.get_list("set-cookie")
    access = next(h for h in set_cookie if h.startswith("ffc_access="))
    refresh = next(h for h in set_cookie if h.startswith("ffc_refresh="))
    for h in (access, refresh):
        assert "HttpOnly" in h and "samesite=lax" in h.lower()
    assert "Path=/api" in access and "Path=/api/v1/auth" in refresh
    me = await client.get("/auth/me")
    assert me.status_code == 200 and me.json()["id"] == u.id


@pytest.mark.asyncio
async def test_refresh_rotates_and_old_token_reuse_revokes_family(client, db_session_factory, monkeypatch):
    u = await _user(db_session_factory)
    await _login(client, u)
    old = _cookie(client, "ffc_refresh").value
    r = await client.post("/auth/refresh", headers=ORIGIN)
    assert r.status_code == 200
    new = _cookie(client, "ffc_refresh").value
    assert new != old
    # Re-presenting the rotated token after the grace window = theft.
    monkeypatch.setattr(settings, "REFRESH_REUSE_GRACE_S", 0)
    _set(client, "ffc_refresh", old, "/api/v1/auth")
    r = await client.post("/auth/refresh", headers=ORIGIN)
    assert r.status_code == 401
    # ...and the legit newest token in that family is dead too.
    _set(client, "ffc_refresh", new, "/api/v1/auth")
    r = await client.post("/auth/refresh", headers=ORIGIN)
    assert r.status_code == 401
    async with db_session_factory() as db:
        rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == u.id))).scalars().all()
        assert rows and all(row.revoked_at is not None for row in rows)


@pytest.mark.asyncio
async def test_reuse_within_grace_window_is_benign(client, db_session_factory):
    u = await _user(db_session_factory)
    await _login(client, u)
    old = _cookie(client, "ffc_refresh").value
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 200
    new = _cookie(client, "ffc_refresh").value
    _set(client, "ffc_refresh", old, "/api/v1/auth")
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 401  # race, not theft
    _set(client, "ffc_refresh", new, "/api/v1/auth")
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 200


@pytest.mark.asyncio
async def test_expired_access_cookie_recovers_via_refresh(client, db_session_factory):
    u = await _user(db_session_factory)
    await _login(client, u)
    expired = create_access_token({"sub": u.id, "token_version": 0}, expires_delta=timedelta(seconds=-5))
    _set(client, "ffc_access", expired, "/api")
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 200
    assert (await client.get("/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_expired_refresh_token_rejected(client, db_session_factory):
    u = await _user(db_session_factory)
    await _login(client, u)
    async with db_session_factory() as db:
        for row in (await db.execute(select(RefreshToken))).scalars():
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_and_clears_cookies(client, db_session_factory):
    u = await _user(db_session_factory)
    await _login(client, u)
    raw = _cookie(client, "ffc_refresh").value
    r = await client.post("/auth/logout", headers=ORIGIN)
    assert r.status_code == 200
    assert _cookie(client, "ffc_access") is None and _cookie(client, "ffc_refresh") is None
    _set(client, "ffc_refresh", raw, "/api/v1/auth")
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 401


@pytest.mark.asyncio
async def test_token_version_bump_kills_refresh(client, db_session_factory):
    """Admin force-logout / suspend / password change bump token_version."""
    u = await _user(db_session_factory)
    await _login(client, u)
    async with db_session_factory() as db:
        user = await db.get(User, u.id)
        user.token_version += 1
        await db.commit()
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 401


@pytest.mark.asyncio
async def test_suspended_user_cannot_refresh(client, db_session_factory):
    u = await _user(db_session_factory)
    await _login(client, u)
    async with db_session_factory() as db:
        user = await db.get(User, u.id)
        user.is_suspended = True
        await db.commit()
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 401


@pytest.mark.asyncio
async def test_csrf_cookie_mutation_requires_allowed_origin(client, db_session_factory):
    u = await _user(db_session_factory)
    await _login(client, u)
    body = {"username": "renamed" + uuid.uuid4().hex[:6]}
    assert (await client.put("/users/me", json=body, headers={"Origin": "null"})).status_code == 403
    assert (await client.put("/users/me", json=body, headers={"Origin": "https://evil.example"})).status_code == 403
    assert (await client.put("/users/me", json=body, headers={"Referer": "https://evil.example/x"})).status_code == 403
    assert (await client.put("/users/me", json=body, headers={"Referer": "http://localhost:3000/settings"})).status_code == 200
    assert (await client.put("/users/me", json=body, headers=ORIGIN)).status_code == 200
    assert (await client.get("/auth/me")).status_code == 200  # safe methods unaffected
    assert (await client.post("/auth/logout", headers={"Origin": "https://evil.example"})).status_code == 403


@pytest.mark.asyncio
async def test_legacy_bearer_still_works_and_upgrades_to_cookie_session(client, db_session_factory):
    u = await _user(db_session_factory)
    legacy = create_access_token({"sub": u.id, "token_version": 0}, expires_delta=timedelta(days=7))
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {legacy}"})
    assert r.status_code == 200
    r = await client.post("/auth/session", headers={"Authorization": f"Bearer {legacy}"})
    assert r.status_code == 200
    assert _cookie(client, "ffc_refresh") is not None
    assert (await client.get("/auth/me")).status_code == 200  # cookie only now


@pytest.mark.asyncio
async def test_access_token_lifetime_is_short():
    import jwt
    tok = create_access_token({"sub": "x"})
    exp = jwt.decode(tok, settings.JWT_SECRET, algorithms=["HS256"])["exp"]
    assert exp - datetime.now(timezone.utc).timestamp() <= 15 * 60 + 1


@pytest.mark.asyncio
async def test_change_password_keeps_this_cookie_session_but_kills_others(client, db_session_factory):
    u = await _user(db_session_factory)
    await _login(client, u)
    other_refresh = _cookie(client, "ffc_refresh").value
    r = await client.post("/users/me/change-password", headers=ORIGIN,
                          json={"current_password": "cookiepass123", "new_password": "newcookiepass456"})
    assert r.status_code == 200
    assert (await client.get("/auth/me")).status_code == 200
    _set(client, "ffc_refresh", other_refresh, "/api/v1/auth")
    assert (await client.post("/auth/refresh", headers=ORIGIN)).status_code == 401


# ─── QA 2026-10-19 NEW-3: guest pages must not log 401s ──────────────────

@pytest.mark.asyncio
async def test_session_probe_is_200_for_guests_and_reports_the_user_when_signed_in(client, db_session_factory):
    r = await client.get("/auth/session")
    assert r.status_code == 200 and r.json() == {"user": None}

    u = await _user(db_session_factory)
    await _login(client, u)
    r = await client.get("/auth/session")
    assert r.status_code == 200 and r.json()["user"]["id"] == u.id
    assert "hashed_password" not in r.json()["user"]

    # A bad/expired access cookie is just "no session", never an error.
    _set(client, "ffc_access", "garbage", "/api")
    r = await client.get("/auth/session")
    assert r.status_code == 200 and r.json() == {"user": None}


@pytest.mark.asyncio
async def test_session_hint_cookie_is_set_with_auth_cookies_and_cleared_on_logout(client, db_session_factory):
    u = await _user(db_session_factory)
    r = await _login(client, u)
    hint = next(h for h in r.headers.get_list("set-cookie") if h.startswith("ffc_session="))
    # Script-readable on purpose (the frontend checks it before probing) and
    # carries no secret -- it's never accepted as a credential.
    assert "HttpOnly" not in hint and "Path=/" in hint and hint.startswith("ffc_session=1;")
    r = await client.post("/auth/refresh", headers=ORIGIN)
    assert any(h.startswith("ffc_session=1;") for h in r.headers.get_list("set-cookie"))

    r = await client.post("/auth/logout", headers=ORIGIN)
    cleared = next(h for h in r.headers.get_list("set-cookie") if h.startswith("ffc_session="))
    assert "Max-Age=0" in cleared or "expires=" in cleared.lower()


@pytest.mark.asyncio
async def test_session_hint_cookie_alone_grants_nothing(client):
    client.cookies.set("ffc_session", "1", domain="test.local", path="/")
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/session")).json() == {"user": None}
