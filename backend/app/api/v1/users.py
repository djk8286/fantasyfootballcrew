from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.user import UserRead, UserPublic, UserUpdate, ChangePasswordRequest
from app.services.auth_service import hash_password, verify_password
from app.api.deps import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Currently just username -- email is left alone (changing it would
    need its own re-verification flow, same reason register/login don't
    let it double as a login-alias-only field) and avatar is a future
    addition once there's a real picker for user (not team) avatars."""
    if data.username is not None and data.username != current_user.username:
        result = await db.execute(select(User).where(User.username == data.username))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already taken")
        current_user.username = data.username
    await db.commit()
    await db.refresh(current_user)
    return current_user


# Same shape as the other password-touching endpoints in auth.py (rate
# limited, generic-ish errors) -- this one's IN-app (already-authenticated
# user changing a password they still remember), unlike forgot/reset-
# password's email-link flow for a password they don't.
@router.post("/me/change-password")
@limiter.limit("5/hour")
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.hashed_password:
        raise HTTPException(
            status_code=400,
            detail="This account signed up with Google and has no password to change.",
        )
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    current_user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return {"message": "Password updated."}


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
