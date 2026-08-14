from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.models.league import League
from app.models.team import Team
from app.models.league_invite import LeagueInvite
from app.models.league_join_request import LeagueJoinRequest
from app.models.notification import Notification
from app.models.password_reset_token import PasswordResetToken
from app.models.email_verification_token import EmailVerificationToken
from app.models.commissioner_digest import CommissionerDigest
from app.schemas.user import UserRead, UserPublic, UserUpdate, ChangePasswordRequest, DeleteAccountRequest
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
    """Permanently and irreversibly deletes the authenticated account
    (hard-delete, not a soft/anonymize -- see the Production Quality
    Hardening plan's account-deletion research: zero soft-delete
    precedent anywhere in this codebase, and hard-delete gets session
    invalidation for free via get_current_user's existing "user row is
    gone -> 401" check).

    Password-based accounts must confirm their current password in the
    body, same as change_password. Google-OAuth accounts have no
    password to check (current_user.hashed_password is None) -- the JWT
    itself, already required to reach this endpoint, is the boundary
    there, matching change_password's own existing split on this.

    Pre-cleanup order matters: leagues/teams are resolved BEFORE the
    User row is deleted, all inside this one request's transaction (no
    intermediate commit), so any block (409) below leaves nothing
    persisted.
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

    # 1. Leagues this user commissions: auto-transfer to another real
    #    (non-CPU) team owner if one exists. If they're the sole real
    #    member, block rather than silently orphaning the league --
    #    they need to transfer commissioner rights or delete the league
    #    themselves first.
    result = await db.execute(select(League).where(League.commissioner_id == current_user.id))
    for league in result.scalars().all():
        teams_result = await db.execute(
            select(Team).where(
                Team.league_id == league.id,
                Team.is_cpu == False,  # noqa: E712
                Team.owner_id != current_user.id,
            )
        )
        successor = teams_result.scalars().first()
        if not successor:
            raise HTTPException(
                status_code=409,
                detail=(
                    f'You\'re the sole real member of "{league.name}" -- transfer '
                    "commissioner rights to someone else or delete the league before "
                    "deleting your account."
                ),
            )
        league.commissioner_id = successor.owner_id

    # 2. Co-commissioner rights are a plain JSON list on League, not an
    #    FK -- no RESTRICT risk, but a stale user_id left behind would be
    #    a silent correctness bug (e.g. still showing up in commissioner
    #    tooling). Scrub it everywhere, not just leagues they own.
    all_leagues_result = await db.execute(select(League))
    for league in all_leagues_result.scalars().all():
        if league.co_commissioner_ids and current_user.id in league.co_commissioner_ids:
            league.co_commissioner_ids.remove(current_user.id)

    # 3. Teams owned/co-owned: null the ownership (same nullable columns
    #    claim_team already relies on), flip back to a CPU team -- the
    #    identical shape bulk_add_cpu_teams already produces -- once no
    #    real owner is left on either side.
    teams_result = await db.execute(
        select(Team).where((Team.owner_id == current_user.id) | (Team.co_owner_id == current_user.id))
    )
    for team in teams_result.scalars().all():
        if team.owner_id == current_user.id:
            team.owner_id = None
        if team.co_owner_id == current_user.id:
            team.co_owner_id = None
        if team.owner_id is None and team.co_owner_id is None:
            team.is_cpu = True

    # 4. Everything else pointing at users.id: null attribution on rows
    #    that outlive the account (invites/join-decisions/digests --
    #    other people's data, not this account's own), hard-delete rows
    #    that ARE this account's own (their pending join requests,
    #    notifications, auth tokens).
    await db.execute(
        update(LeagueInvite).where(LeagueInvite.invited_by_user_id == current_user.id)
        .values(invited_by_user_id=None)
    )
    await db.execute(
        update(LeagueInvite).where(LeagueInvite.accepted_by_user_id == current_user.id)
        .values(accepted_by_user_id=None)
    )
    await db.execute(
        update(LeagueJoinRequest).where(LeagueJoinRequest.decided_by_user_id == current_user.id)
        .values(decided_by_user_id=None)
    )
    await db.execute(
        update(CommissionerDigest).where(CommissionerDigest.generated_by == current_user.id)
        .values(generated_by=None)
    )
    await db.execute(delete(LeagueJoinRequest).where(LeagueJoinRequest.requested_by_user_id == current_user.id))
    await db.execute(delete(Notification).where(Notification.user_id == current_user.id))
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == current_user.id))
    await db.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == current_user.id))

    # 5. The account itself. get_current_user 401s on the very next
    #    request for any token tied to this id -- no separate session-
    #    invalidation step needed.
    await db.delete(current_user)
    await db.commit()
    return {"status": "ok"}


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
