"""Cookie sessions: short-lived access JWT + rotating, revocable refresh token.

Cookies (all HttpOnly, SameSite=Lax, Secure in production, host-only --
no Domain attribute, so they belong to whatever first-party host served
the /api proxy, i.e. fantasyfootballcrew.com):
  ffc_access   access JWT, Path=/api, ~15 min
  ffc_refresh  raw refresh token, Path=/api/v1/auth, 30 days
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import create_access_token, hash_token

ACCESS_COOKIE = "ffc_access"
REFRESH_COOKIE = "ffc_refresh"
SESSION_HINT_COOKIE = "ffc_session"  # NOT a credential: readable "a session may exist" flag
ACCESS_PATH = "/api"
REFRESH_PATH = "/api/v1/auth"


class RefreshError(Exception):
    """Refresh refused. ``reason`` is for logs/tests only, never shown."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone=True columns.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _secure() -> bool:
    if settings.COOKIE_SECURE is not None:
        return settings.COOKIE_SECURE
    return settings.ENVIRONMENT.lower() == "production"


def access_token_for(user: User) -> str:
    return create_access_token({"sub": user.id, "email": user.email, "token_version": user.token_version})


def set_auth_cookies(response: Response, access_token: str, refresh_raw: str) -> None:
    common = dict(httponly=True, secure=_secure(), samesite="lax")
    response.set_cookie(ACCESS_COOKIE, access_token, path=ACCESS_PATH,
                        max_age=int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60), **common)
    response.set_cookie(REFRESH_COOKIE, refresh_raw, path=REFRESH_PATH,
                        max_age=int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400), **common)
    # Script-readable, value-less hint so the frontend only probes/refreshes
    # a session when one may exist -- guests then make no auth calls at all
    # (and log no 401s). Carries no secret; forging it just costs one 401.
    response.set_cookie(SESSION_HINT_COOKIE, "1", path="/", httponly=False, secure=_secure(), samesite="lax",
                        max_age=int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400))


def clear_auth_cookies(response: Response) -> None:
    common = dict(httponly=True, secure=_secure(), samesite="lax")
    response.delete_cookie(ACCESS_COOKIE, path=ACCESS_PATH, **common)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, **common)
    response.delete_cookie(SESSION_HINT_COOKIE, path="/", httponly=False, secure=_secure(), samesite="lax")


async def _new_refresh(db: AsyncSession, user: User, family_id: str) -> tuple[RefreshToken, str]:
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        id=str(uuid.uuid4()), user_id=user.id, family_id=family_id,
        token_hash=hash_token(raw), token_version=user.token_version,
        expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(row)
    return row, raw


async def start_session(db: AsyncSession, user: User, response: Response) -> str:
    """New login: new refresh family + cookies. Returns the access JWT."""
    _, raw = await _new_refresh(db, user, family_id=str(uuid.uuid4()))
    await db.commit()
    access = access_token_for(user)
    set_auth_cookies(response, access, raw)
    return access


async def rotate(db: AsyncSession, raw: str | None, response: Response) -> User:
    """Exchange a refresh token for a fresh pair. Raises RefreshError."""
    if not raw:
        raise RefreshError("missing")
    row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))).scalar_one_or_none()
    if row is None:
        raise RefreshError("unknown")
    now = _now()
    if row.revoked_at is not None:
        if row.replaced_by_id and now - _aware(row.revoked_at) <= timedelta(seconds=settings.REFRESH_REUSE_GRACE_S):
            # Another tab rotated this a moment ago; the browser's cookie
            # jar already holds the replacement. Refuse without nuking.
            raise RefreshError("race")
        await revoke_family(db, row.family_id)
        raise RefreshError("reuse")
    if _aware(row.expires_at) <= now:
        raise RefreshError("expired")
    user = await db.get(User, row.user_id)
    if user is None or user.is_suspended or user.token_version != row.token_version:
        await revoke_family(db, row.family_id)
        raise RefreshError("revoked_user")
    new_row, new_raw = await _new_refresh(db, user, row.family_id)
    row.revoked_at = now
    row.replaced_by_id = new_row.id
    await db.commit()
    set_auth_cookies(response, access_token_for(user), new_raw)
    return user


async def revoke_family(db: AsyncSession, family_id: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()


async def revoke_by_raw(db: AsyncSession, raw: str | None) -> None:
    if not raw:
        return
    row = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))).scalar_one_or_none()
    if row is not None:
        await revoke_family(db, row.family_id)
