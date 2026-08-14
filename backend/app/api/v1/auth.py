import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.models.password_reset_token import PasswordResetToken
from app.schemas.user import UserCreate, UserRead, UserLogin, ForgotPasswordRequest, ResetPasswordRequest
from app.services.auth_service import hash_password, verify_password, needs_rehash, create_access_token, hash_token
from app.services.email_service import send_password_reset_email
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_TOKEN_LIFETIME = timedelta(hours=1)


# Registration is a rare, one-time action for a real user, so a tight limit
# doesn't cost legitimate traffic anything -- it just blocks mass account
# creation. slowapi needs the `request` param present (even though it's
# only read by the decorator, not the function body) to key off the caller's IP.
@router.post("/register", response_model=UserRead)
@limiter.limit("5/hour")
async def register(request: Request, user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=hash_password(user_data.password) if user_data.password else None,
        provider=user_data.provider,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == login_data.email))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if needs_rehash(user.hashed_password):
        # Transparent migration off the legacy SHA-256 hash format --
        # see auth_service.needs_rehash. No forced reset, no visible
        # change; this just quietly happens on the next successful
        # login for any account that hasn't logged in since the switch.
        user.hashed_password = hash_password(login_data.password)
        await db.commit()

    token = create_access_token({"sub": user.id, "email": user.email, "token_version": user.token_version})
    return {"access_token": token, "token_type": "bearer", "user": UserRead.model_validate(user)}


# Deliberately tight limit -- this is the endpoint that emails/logs a
# working reset link, so it's the one that most needs protecting from
# being hammered (spamming someone's inbox, or spamming server logs with
# reset links while no email provider is configured).
@router.post("/forgot-password")
@limiter.limit("3/hour")
async def forgot_password(request: Request, data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    # Same response whether the email exists, doesn't, or belongs to an
    # OAuth-only account with no password to reset (hashed_password is
    # None for those) -- anything else would let this endpoint be used to
    # discover which emails are registered.
    generic_response = {"message": "If that email is registered, a password reset link has been sent."}

    if not user or not user.hashed_password:
        return generic_response

    raw_token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + RESET_TOKEN_LIFETIME,
    ))
    await db.commit()

    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
    await send_password_reset_email(user.email, reset_link)

    return generic_response


@router.post("/reset-password")
@limiter.limit("10/hour")
async def reset_password(request: Request, data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(data.token))
    )
    reset_token = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    expired = reset_token and reset_token.expires_at.replace(tzinfo=timezone.utc) < now
    if not reset_token or reset_token.used_at is not None or expired:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please request a new one.")

    user_result = await db.execute(select(User).where(User.id == reset_token.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please request a new one.")

    user.hashed_password = hash_password(data.new_password)
    # Invalidates every token issued before this reset -- a stolen
    # token no longer survives a password reset. See User.token_version.
    user.token_version += 1
    reset_token.used_at = now
    await db.commit()

    return {"message": "Password updated. You can now log in with your new password."}


@router.get("/me", response_model=UserRead)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
