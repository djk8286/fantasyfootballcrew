"""
Tests for admin user management (search/pagination, suspend, force-logout,
password reset / verification resend, admin grant/revoke) and the admin
audit log that records every admin mutation.
"""
import uuid
import pytest
from sqlalchemy import select

from app.models.user import User
from app.models.league import League, LeagueType
from app.models.admin_audit_log import AdminAuditLog
from app.models.password_reset_token import PasswordResetToken
from app.models.email_verification_token import EmailVerificationToken
from app.services.auth_service import create_access_token
from tests.test_admin import _make_user


async def _admin_client(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    client.headers["Authorization"] = f"Bearer {token}"
    return admin


async def _audit_rows(factory, action=None):
    async with factory() as db:
        q = select(AdminAuditLog)
        if action:
            q = q.where(AdminAuditLog.action == action)
        return (await db.execute(q)).scalars().all()


async def _reload(factory, user_id):
    async with factory() as db:
        return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


@pytest.mark.asyncio
async def test_non_admin_gets_403_on_every_new_route(client, db_session_factory):
    _u, token = await _make_user(db_session_factory)
    target, _ = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    assert (await client.get("/admin/audit-log")).status_code == 403
    for action in ["suspend", "unsuspend", "force-logout", "send-password-reset", "resend-verification"]:
        r = await client.post(f"/admin/users/{target.id}/{action}", json={})
        assert r.status_code == 403, action
    assert (await client.post(f"/admin/users/{target.id}/admin", json={"is_admin": True})).status_code == 403


@pytest.mark.asyncio
async def test_user_search_and_pagination(client, db_session_factory):
    await _admin_client(client, db_session_factory)
    async with db_session_factory() as db:
        for i in range(5):
            db.add(User(id=str(uuid.uuid4()), email=f"zebra{i}@Example.com", username=f"Zebra{i}", hashed_password="x"))
        await db.commit()

    r = await client.get("/admin/users", params={"q": "ZEBRA", "limit": 2, "offset": 0})
    data = r.json()
    assert r.status_code == 200
    assert data["total"] == 5 and len(data["items"]) == 2 and data["limit"] == 2

    page2 = (await client.get("/admin/users", params={"q": "zebra", "limit": 2, "offset": 2})).json()
    page3 = (await client.get("/admin/users", params={"q": "zebra", "limit": 2, "offset": 4})).json()
    ids = [u["id"] for u in data["items"] + page2["items"] + page3["items"]]
    assert len(ids) == 5 and len(set(ids)) == 5

    by_email = (await client.get("/admin/users", params={"q": "example.com"})).json()
    assert by_email["total"] == 5
    assert (await client.get("/admin/users", params={"status": "admin"})).json()["total"] == 1
    assert (await client.get("/admin/users", params={"status": "bogus"})).status_code == 422


@pytest.mark.asyncio
async def test_suspend_blocks_existing_token_login_and_is_reversible(client, db_session_factory):
    admin = await _admin_client(client, db_session_factory)
    victim, victim_token = await _make_user(db_session_factory)
    admin_auth = client.headers["Authorization"]

    r = await client.post(f"/admin/users/{victim.id}/suspend", json={"reason": "spam"})
    assert r.status_code == 200 and r.json()["is_suspended"] is True
    assert r.json()["suspended_reason"] == "spam"

    # Existing session is dead.
    client.headers["Authorization"] = f"Bearer {victim_token}"
    assert (await client.get("/auth/me")).status_code == 401
    # Even a freshly-minted token (current token_version) is refused.
    fresh = await _reload(db_session_factory, victim.id)
    client.headers["Authorization"] = "Bearer " + create_access_token(
        {"sub": fresh.id, "email": fresh.email, "token_version": fresh.token_version})
    assert (await client.get("/auth/me")).status_code == 403
    # Login refused (correct password).
    client.headers.pop("Authorization")
    r = await client.post("/auth/login", json={"email": victim.email, "password": "realpassword123"})
    assert r.status_code == 403 and r.json()["detail"] == "Account suspended"
    # Wrong password still just 401 -- suspension isn't leaked.
    r = await client.post("/auth/login", json={"email": victim.email, "password": "wrongpassword1"})
    assert r.status_code == 401

    client.headers["Authorization"] = admin_auth
    r = await client.post(f"/admin/users/{victim.id}/unsuspend")
    assert r.status_code == 200 and r.json()["is_suspended"] is False
    client.headers.pop("Authorization")
    r = await client.post("/auth/login", json={"email": victim.email, "password": "realpassword123"})
    assert r.status_code == 200

    actions = sorted(a.action for a in await _audit_rows(db_session_factory))
    assert actions == ["user.suspend", "user.unsuspend"]
    suspend = (await _audit_rows(db_session_factory, "user.suspend"))[0]
    assert suspend.admin_user_id == admin.id and suspend.target_label == victim.username
    assert suspend.details == {"reason": "spam"}


@pytest.mark.asyncio
async def test_cannot_suspend_self(client, db_session_factory):
    admin = await _admin_client(client, db_session_factory)
    assert (await client.post(f"/admin/users/{admin.id}/suspend", json={})).status_code == 400
    assert await _audit_rows(db_session_factory) == []


@pytest.mark.asyncio
async def test_force_logout_kills_existing_sessions_only(client, db_session_factory):
    await _admin_client(client, db_session_factory)
    victim, victim_token = await _make_user(db_session_factory)
    assert (await client.post(f"/admin/users/{victim.id}/force-logout")).status_code == 200

    client.headers["Authorization"] = f"Bearer {victim_token}"
    assert (await client.get("/auth/me")).status_code == 401
    client.headers.pop("Authorization")
    r = await client.post("/auth/login", json={"email": victim.email, "password": "realpassword123"})
    assert r.status_code == 200
    assert len(await _audit_rows(db_session_factory, "user.force_logout")) == 1


@pytest.mark.asyncio
async def test_send_password_reset_uses_existing_flow(client, db_session_factory):
    await _admin_client(client, db_session_factory)
    victim, _ = await _make_user(db_session_factory)
    r = await client.post(f"/admin/users/{victim.id}/send-password-reset")
    assert r.status_code == 200
    assert "token" not in r.text  # the admin never sees the link
    async with db_session_factory() as db:
        tokens = (await db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == victim.id))).scalars().all()
    assert len(tokens) == 1
    assert len(await _audit_rows(db_session_factory, "user.send_password_reset")) == 1


@pytest.mark.asyncio
async def test_send_password_reset_400s_for_oauth_only_account(client, db_session_factory):
    await _admin_client(client, db_session_factory)
    async with db_session_factory() as db:
        oauth = User(id=str(uuid.uuid4()), email="g@test.local", username="googler", provider="google", hashed_password=None)
        db.add(oauth)
        await db.commit()
    assert (await client.post(f"/admin/users/{oauth.id}/send-password-reset")).status_code == 400
    assert await _audit_rows(db_session_factory) == []


@pytest.mark.asyncio
async def test_resend_verification(client, db_session_factory):
    await _admin_client(client, db_session_factory)
    victim, _ = await _make_user(db_session_factory)
    assert (await client.post(f"/admin/users/{victim.id}/resend-verification")).status_code == 200
    async with db_session_factory() as db:
        n = len((await db.execute(select(EmailVerificationToken).where(EmailVerificationToken.user_id == victim.id))).scalars().all())
        v = await db.get(User, victim.id)
        v.email_verified = True
        await db.commit()
    assert n == 1
    assert (await client.post(f"/admin/users/{victim.id}/resend-verification")).status_code == 400


@pytest.mark.asyncio
async def test_grant_and_revoke_admin_with_guards(client, db_session_factory):
    admin = await _admin_client(client, db_session_factory)
    other, _ = await _make_user(db_session_factory)

    # Can't touch your own flag.
    assert (await client.post(f"/admin/users/{admin.id}/admin", json={"is_admin": False})).status_code == 400

    r = await client.post(f"/admin/users/{other.id}/admin", json={"is_admin": True})
    assert r.status_code == 200 and r.json()["is_admin"] is True
    r = await client.post(f"/admin/users/{other.id}/admin", json={"is_admin": False})
    assert r.status_code == 200 and r.json()["is_admin"] is False

    actions = sorted(a.action for a in await _audit_rows(db_session_factory))
    assert actions == ["user.grant_admin", "user.revoke_admin"]


@pytest.mark.asyncio
async def test_delete_user_and_league_are_audited(client, db_session_factory):
    admin = await _admin_client(client, db_session_factory)
    victim, _ = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Doomed League", commissioner_id=admin.id,
                        league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()

    assert (await client.delete(f"/admin/users/{victim.id}")).status_code == 200
    assert (await client.delete(f"/admin/leagues/{league.id}")).status_code == 200

    r = await client.get("/admin/audit-log")
    assert r.status_code == 200
    items = r.json()["items"]
    assert r.json()["total"] == 2
    by_action = {i["action"]: i for i in items}
    assert by_action["user.delete"]["target_label"] == victim.username
    assert by_action["user.delete"]["details"] == {"email": victim.email}
    assert by_action["league.delete"]["target_label"] == "Doomed League"
    assert all(i["admin_username"] == admin.username for i in items)

    scoped = (await client.get("/admin/audit-log", params={"target_id": league.id})).json()
    assert scoped["total"] == 1 and scoped["items"][0]["action"] == "league.delete"


@pytest.mark.asyncio
async def test_failed_delete_writes_no_audit_row(client, db_session_factory):
    await _admin_client(client, db_session_factory)
    assert (await client.delete(f"/admin/users/{uuid.uuid4()}")).status_code == 404
    assert await _audit_rows(db_session_factory) == []
