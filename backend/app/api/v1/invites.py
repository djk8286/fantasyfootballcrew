import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import settings
from app.core.limiter import limiter
from app.models.league import League, LeagueVisibility
from app.models.league_invite import LeagueInvite, InviteStatus
from app.models.league_join_request import LeagueJoinRequest, JoinRequestStatus
from app.models.user import User
from app.models.notification import NotificationType
from app.schemas.league_invite import InviteCreateRequest, InviteRead, InviteLandingRead
from app.schemas.league_join_request import JoinRequestCreate, JoinRequestRead, JoinRequestDecision
from app.services.auth_service import hash_token
from app.services.email_service import send_league_invite_email
from app.services.notification_service import create_notification
from app.api.deps import get_current_user, require_commissioner

# No router-level prefix -- unlike every other feature router, this one
# genuinely needs two different path shapes: /leagues/{league_id}/invites
# (commissioner-facing) and /invites/{token} (public, token-based). Every
# other router in this app only ever needs one fixed prefix.
router = APIRouter(tags=["invites"])

INVITE_TOKEN_LIFETIME = timedelta(days=14)  # longer than password reset's 1hr -- a social invite, not an account-recovery link
MAX_INVITES_PER_REQUEST = 20


async def _get_league_or_404(league_id: str, db: AsyncSession) -> League:
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return league


def _display_status(invite: LeagueInvite) -> str:
    """EXPIRED is never written to the DB -- it's derived at read time,
    same reasoning as reset_password's own expiry check."""
    if invite.status == InviteStatus.PENDING and invite.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return "expired"
    return invite.status.value


@router.post("/leagues/{league_id}/invites", response_model=list[InviteRead], status_code=201)
@limiter.limit("10/hour")
async def send_invites(
    request: Request,
    league_id: str,
    data: InviteCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league_or_404(league_id, db)
    require_commissioner(league, current_user)

    if len(data.emails) > MAX_INVITES_PER_REQUEST:
        raise HTTPException(status_code=422, detail=f"Cannot send more than {MAX_INVITES_PER_REQUEST} invites at once")

    created: list[LeagueInvite] = []
    for email in data.emails:
        raw_token = secrets.token_urlsafe(32)
        invite = LeagueInvite(
            league_id=league_id,
            invited_email=email,
            invited_by_user_id=current_user.id,
            personal_message=data.message,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + INVITE_TOKEN_LIFETIME,
        )
        db.add(invite)
        created.append(invite)
        invite_link = f"{settings.FRONTEND_URL}/invites/{raw_token}"
        await send_league_invite_email(email, league.name, current_user.username, data.message, invite_link)

    await db.commit()
    for invite in created:
        await db.refresh(invite)
    return [InviteRead(id=i.id, invited_email=i.invited_email, status=_display_status(i),
                        created_at=i.created_at, expires_at=i.expires_at, accepted_at=i.accepted_at)
            for i in created]


@router.get("/leagues/{league_id}/invites", response_model=list[InviteRead])
async def list_invites(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league_or_404(league_id, db)
    require_commissioner(league, current_user)
    result = await db.execute(
        select(LeagueInvite).where(LeagueInvite.league_id == league_id).order_by(LeagueInvite.created_at.desc())
    )
    invites = result.scalars().all()
    return [InviteRead(id=i.id, invited_email=i.invited_email, status=_display_status(i),
                        created_at=i.created_at, expires_at=i.expires_at, accepted_at=i.accepted_at)
            for i in invites]


@router.delete("/leagues/{league_id}/invites/{invite_id}")
@limiter.limit("30/hour")
async def revoke_invite(
    request: Request,
    league_id: str,
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league_or_404(league_id, db)
    require_commissioner(league, current_user)
    result = await db.execute(
        select(LeagueInvite).where(LeagueInvite.id == invite_id, LeagueInvite.league_id == league_id)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail="Only a pending invite can be revoked")
    invite.status = InviteStatus.REVOKED
    await db.commit()
    return {"status": "ok"}


@router.get("/invites/{token}", response_model=InviteLandingRead)
async def get_invite_by_token(token: str, db: AsyncSession = Depends(get_db)):
    """Public, no auth required -- the landing page needs to show league
    name/inviter before the recipient has necessarily logged in or
    registered yet."""
    result = await db.execute(select(LeagueInvite).where(LeagueInvite.token_hash == hash_token(token)))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    league_result = await db.execute(select(League).where(League.id == invite.league_id))
    league = league_result.scalar_one_or_none()
    inviter_result = await db.execute(select(User).where(User.id == invite.invited_by_user_id))
    inviter = inviter_result.scalar_one_or_none()
    if not league or not inviter:
        raise HTTPException(status_code=404, detail="Invite not found")

    return InviteLandingRead(
        league_id=league.id,
        league_name=league.name,
        league_description=league.description,
        inviter_username=inviter.username,
        personal_message=invite.personal_message,
        usable=_display_status(invite) == "pending",
    )


@router.post("/invites/{token}/accept")
@limiter.limit("20/hour")
async def accept_invite(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(LeagueInvite).where(LeagueInvite.token_hash == hash_token(token)))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if _display_status(invite) != "pending":
        raise HTTPException(status_code=400, detail="This invite is no longer valid")

    # Token-possession-based, not email-matching -- see LeagueInvite's
    # docstring. Whoever holds the link and is logged in gets credit for
    # accepting it, regardless of whether their account email matches
    # invited_email.
    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = datetime.now(timezone.utc)
    invite.accepted_by_user_id = current_user.id

    league = await _get_league_or_404(invite.league_id, db)
    # Notify whoever specifically sent this invite, not every commissioner
    # -- they're the one with context on who they invited and why.
    await create_notification(
        db, invite.invited_by_user_id, NotificationType.LEAGUE_INVITE_ACCEPTED,
        f"{current_user.username} accepted your invite to {league.name}.",
        league_id=league.id, link=f"/leagues/{league.id}/commissioner",
    )

    await db.commit()
    return {"status": "ok", "league_id": invite.league_id}


# ─── Join requests ──────────────────────────────────────────────────
# The "or approval" half of Invite-only: a user who found the league
# through discovery asks the commissioner for access, rather than the
# commissioner reaching out first (LeagueInvite). Only meaningful for
# INVITE_ONLY leagues -- OPEN leagues are joined directly via
# claim_team, PRIVATE leagues aren't discoverable enough to request
# against in the first place.

async def _username_map(db: AsyncSession, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    result = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
    return {uid: username for uid, username in result.all()}


async def _notify_commissioners(db: AsyncSession, league: League, type: NotificationType, message: str, link: str) -> None:
    """Unlike LeagueInvite's accept (one specific inviter has context),
    a join request isn't addressed to anyone in particular -- any
    commissioner or co-commissioner should see it and can act on it."""
    for user_id in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        await create_notification(db, user_id, type, message, league_id=league.id, link=link)


@router.post("/leagues/{league_id}/join-requests", response_model=JoinRequestRead, status_code=201)
@limiter.limit("20/hour")
async def create_join_request(
    request: Request,
    league_id: str,
    data: JoinRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league_or_404(league_id, db)
    if league.visibility != LeagueVisibility.INVITE_ONLY:
        raise HTTPException(
            status_code=400,
            detail="Join requests are only for invite-only leagues -- open leagues can be joined directly, private leagues aren't discoverable.",
        )

    # Application-level dedup, not a DB constraint -- a DENIED request can
    # be resubmitted later, just not spammed while one is still PENDING.
    existing = await db.execute(
        select(LeagueJoinRequest).where(
            LeagueJoinRequest.league_id == league_id,
            LeagueJoinRequest.requested_by_user_id == current_user.id,
            LeagueJoinRequest.status == JoinRequestStatus.PENDING,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="You already have a pending request for this league")

    join_request = LeagueJoinRequest(
        league_id=league_id,
        requested_by_user_id=current_user.id,
        message=data.message,
    )
    db.add(join_request)

    await _notify_commissioners(
        db, league, NotificationType.JOIN_REQUEST_RECEIVED,
        f"{current_user.username} requested to join {league.name}.",
        link=f"/leagues/{league_id}/commissioner",
    )

    await db.commit()
    await db.refresh(join_request)
    return JoinRequestRead(
        id=join_request.id, league_id=join_request.league_id,
        requested_by_user_id=join_request.requested_by_user_id,
        requester_username=current_user.username,
        message=join_request.message, status=join_request.status.value,
        created_at=join_request.created_at, decided_at=join_request.decided_at,
    )


@router.get("/leagues/{league_id}/join-requests", response_model=list[JoinRequestRead])
async def list_join_requests(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league_or_404(league_id, db)
    require_commissioner(league, current_user)
    result = await db.execute(
        select(LeagueJoinRequest).where(LeagueJoinRequest.league_id == league_id).order_by(LeagueJoinRequest.created_at.desc())
    )
    requests = result.scalars().all()
    usernames = await _username_map(db, {r.requested_by_user_id for r in requests})
    return [
        JoinRequestRead(
            id=r.id, league_id=r.league_id, requested_by_user_id=r.requested_by_user_id,
            requester_username=usernames.get(r.requested_by_user_id, "Unknown"),
            message=r.message, status=r.status.value,
            created_at=r.created_at, decided_at=r.decided_at,
        )
        for r in requests
    ]


@router.post("/leagues/{league_id}/join-requests/{request_id}/decision")
@limiter.limit("30/hour")
async def decide_join_request(
    request: Request,
    league_id: str,
    request_id: str,
    data: JoinRequestDecision,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = await _get_league_or_404(league_id, db)
    require_commissioner(league, current_user)
    result = await db.execute(
        select(LeagueJoinRequest).where(LeagueJoinRequest.id == request_id, LeagueJoinRequest.league_id == league_id)
    )
    join_request = result.scalar_one_or_none()
    if not join_request:
        raise HTTPException(status_code=404, detail="Join request not found")
    if join_request.status != JoinRequestStatus.PENDING:
        raise HTTPException(status_code=400, detail="This request has already been decided")

    join_request.status = JoinRequestStatus.APPROVED if data.action == "approve" else JoinRequestStatus.DENIED
    join_request.decided_by_user_id = current_user.id
    join_request.decided_at = datetime.now(timezone.utc)

    decision_word = "approved" if join_request.status == JoinRequestStatus.APPROVED else "denied"
    await create_notification(
        db, join_request.requested_by_user_id, NotificationType.JOIN_REQUEST_DECIDED,
        f"Your request to join {league.name} was {decision_word}.",
        league_id=league.id, link=f"/leagues/{league.id}",
    )

    await db.commit()
    return {"status": "ok", "decision": join_request.status.value}
