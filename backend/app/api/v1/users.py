from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.user import UserRead, UserPublic, UserUpdate, ChangePasswordRequest, DeleteAccountRequest
from app.services.auth_service import hash_password, verify_password
from app.services.account_deletion_service import delete_user_account
from app.api.deps import get_current_user
from app.core.avatars import validate_avatar_url

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
    """Username and avatar. Email is left alone (changing it would need
    its own re-verification flow, same reason register/login don't let
    it double as a login-alias-only field). avatar_url uses the same
    "ffc-avatar:<id>" scheme as Team.avatar_url (see frontend's
    TEAM_AVATARS) -- not validated against that list here, same as team
    avatars aren't either, so a future avatar set doesn't need a backend
    change to go with it."""
    if data.username is not None and data.username != current_user.username:
        result = await db.execute(select(User).where(User.username == data.username))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already taken")
        current_user.username = data.username
    if data.avatar_url is not None:
        validate_avatar_url(data.avatar_url)
        current_user.avatar_url = data.avatar_url
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
    # Invalidates every token issued before this change -- a stolen
    # token no longer survives a password change. See User.token_version.
    current_user.token_version += 1
    await db.commit()
    return {"message": "Password updated."}


@router.delete("/me")
@limiter.limit("5/hour")
async def delete_me(
    request: Request,
    data: DeleteAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently and irreversibly deletes the authenticated account --
    see account_deletion_service.delete_user_account for the actual
    cleanup (shared with the admin-triggered DELETE /admin/users/{id}).

    Password-based accounts must confirm their current password in the
    body, same as change_password. Google-OAuth accounts have no
    password to check (current_user.hashed_password is None) -- the JWT
    itself, already required to reach this endpoint, is the boundary
    there, matching change_password's own existing split on this.
    """
    if current_user.hashed_password:
        # 400, not 401 -- the JWT itself is already valid (that's how we
        # got past get_current_user); a wrong confirmation password here
        # is an app-level check failing, not an auth failure. Returning
        # 401 would trip api-client.ts's "401 with a token attached means
        # the token itself is bad" handling and silently force-logout/
        # redirect the user mid-flow instead of showing them the inline
        # "wrong password" error.
        if not data.password or not verify_password(data.password, current_user.hashed_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

    await delete_user_account(db, current_user)
    await db.commit()
    return {"status": "ok"}


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
