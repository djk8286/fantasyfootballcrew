from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.user import User
from app.models.league import League, LeagueVisibility
from app.models.team import Team
from app.models.league_invite import LeagueInvite, InviteStatus
from app.models.league_join_request import LeagueJoinRequest, JoinRequestStatus
from app.services.auth_service import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like get_current_user, but returns None instead of raising when no/invalid token is given."""
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    return result.scalar_one_or_none()


def require_commissioner(league: League, current_user: User) -> None:
    """Raise 403 unless current_user is the league's commissioner or a co-commissioner."""
    allowed_ids = {league.commissioner_id, *(league.co_commissioner_ids or [])}
    if current_user.id not in allowed_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Commissioner access required")


def require_team_or_league_access(team: Team, league: League, current_user: User) -> None:
    """Raise 403 unless current_user owns/co-owns `team`, or is `league`'s
    commissioner/co-commissioner. Moved here from teams.py (was
    module-private, `_require_team_or_league_access`) so drafts.py can share
    it instead of re-deriving the same allowed-ids set."""
    allowed_ids = {team.owner_id, team.co_owner_id, league.commissioner_id, *(league.co_commissioner_ids or [])}
    if current_user.id not in allowed_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this team")


async def require_league_participant(league: League, current_user: User, db: AsyncSession) -> None:
    """Raise 403 unless current_user owns/co-owns *some* team in `league`,
    or is its commissioner/co-commissioner -- i.e. is a legitimate member of
    this league at all, not necessarily of any specific team in it.

    For actions where it doesn't matter which team you are, only that
    you're actually in this league -- namely nudging a CPU-controlled
    team's draft pick forward, which any real participant should be able
    to do (there's no human on the other end to protect), but a total
    stranger to the league should not.
    """
    allowed_ids = {league.commissioner_id, *(league.co_commissioner_ids or [])}
    if current_user.id in allowed_ids:
        return
    result = await db.execute(
        select(Team.id).where(
            Team.league_id == league.id,
            (Team.owner_id == current_user.id) | (Team.co_owner_id == current_user.id),
        )
    )
    if result.first() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant in this league")


async def user_can_join_league(db: AsyncSession, league: League, user: User) -> bool:
    """Whether `user` is allowed to claim a team/co-owner slot in
    `league`, given its visibility. Shared by teams.py's claim_team/
    claim_co_owner (Step 6 -- this is what actually enforces visibility,
    not just discovery listing) and leagues.py's viewer_join_status
    computation (Step 7), so the two can't drift out of sync.

    OPEN -> anyone. Commissioner/co-commissioner -> always, regardless of
    visibility (they made the league). Otherwise (INVITE_ONLY, PRIVATE)
    -> only if this user holds an ACCEPTED LeagueInvite or an APPROVED
    LeagueJoinRequest for this league. PRIVATE leagues have no join-
    request path (see invites.py's create_join_request), so an accepted
    invite is the only route in for them.
    """
    if league.visibility == LeagueVisibility.OPEN:
        return True
    if user.id in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        return True

    invite_result = await db.execute(
        select(LeagueInvite.id).where(
            LeagueInvite.league_id == league.id,
            LeagueInvite.accepted_by_user_id == user.id,
            LeagueInvite.status == InviteStatus.ACCEPTED,
        )
    )
    if invite_result.first() is not None:
        return True

    request_result = await db.execute(
        select(LeagueJoinRequest.id).where(
            LeagueJoinRequest.league_id == league.id,
            LeagueJoinRequest.requested_by_user_id == user.id,
            LeagueJoinRequest.status == JoinRequestStatus.APPROVED,
        )
    )
    return request_result.first() is not None
