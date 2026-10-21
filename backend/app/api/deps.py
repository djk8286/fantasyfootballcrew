from fastapi import Depends, HTTPException, Request, status
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

ACCESS_COOKIE = "ffc_access"


def _request_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """Access token from the HttpOnly ``ffc_access`` cookie (primary), or
    an ``Authorization: Bearer`` header (transitional -- pre-cookie
    clients and API/test callers; slated for removal after one release)."""
    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(ACCESS_COOKIE) or None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _request_token(request, credentials)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # A token issued before the account's last password change/reset
    # carries a stale (or absent, for a token issued before this check
    # existed) token_version claim -- reject it rather than leak *why*
    # via a distinct error message. See User.token_version.
    if payload.get("token_version", 0) != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # Belt-and-braces: suspending bumps token_version (so the check above
    # already rejects pre-suspension tokens), but this also covers any
    # token minted while suspended through some other path.
    if user.is_suspended:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account suspended")

    return user


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like get_current_user, but returns None instead of raising when no/invalid token is given."""
    token = _request_token(request, credentials)
    if token is None:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if user is None or payload.get("token_version", 0) != user.token_version or user.is_suspended:
        return None
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Gate for app/api/v1/admin.py -- the read-only dev/management
    dashboard. Deliberately its own flag rather than "is the site owner"
    check on a hardcoded email, so more than one person (other employees/
    collaborators) can be granted access later without a code change."""
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


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


async def is_league_participant(league: League, user: User | None, db: AsyncSession) -> bool:
    """Owns/co-owns some team in `league`, or is its commissioner/co-commissioner."""
    if user is None:
        return False
    if user.id in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        return True
    result = await db.execute(
        select(Team.id).where(
            Team.league_id == league.id,
            (Team.owner_id == user.id) | (Team.co_owner_id == user.id),
        )
    )
    return result.first() is not None


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
    if not await is_league_participant(league, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant in this league")


# ─── Who may see a league ───────────────────────────────────────────
# OPEN and INVITE_ONLY leagues (the ones the public listing shows) are
# readable by anyone, rosters included, same as every fantasy site.
# PRIVATE leagues: members and accepted invitees / approved join requests
# only -- EVERY read (standings, schedule, activity, trades, waivers,
# draft, settings, teams, rosters...): 401 for guests, 403 for anyone
# else logged in. GET /leagues/{id} still answers a non-viewer with the
# league's name (in the 401/403 detail) so pages can say "Log in to see
# <league>". Lineups (slot assignments, starters, lineup issues,
# projected totals and box scores built from them) need a login in every
# league. Routes opt in with dependencies=[Depends(require_league_view)]
# (league_id path/query param), require_team_league_view (team_id) or
# require_draft_league_view (draft_id); tests/test_private_league_reads.py
# walks every GET route.

async def can_view_rosters(league: League, viewer: User | None, db: AsyncSession) -> bool:
    """PRIVATE leagues: members, plus anyone holding an accepted invite or
    approved join request (user_can_join_league), so an invitee can still
    look the league over and pick a team to claim."""
    if league.visibility != LeagueVisibility.PRIVATE:
        return True
    if viewer is None:
        return False
    return await is_league_participant(league, viewer, db) or await user_can_join_league(db, league, viewer)


async def can_view_lineups(league: League, viewer: User | None, db: AsyncSession) -> bool:
    return viewer is not None and await can_view_rosters(league, viewer, db)


async def require_league_read(league: League, current_user: User | None, db: AsyncSession) -> None:
    """Gate for lineup data: 401 for guests, 403 for a PRIVATE league the
    user isn't in or invited to (see can_view_lineups)."""
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not await can_view_rosters(league, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant in this league")


async def league_view_or_raise(league: League, viewer: User | None, db: AsyncSession) -> None:
    """The PRIVATE-league read gate: no-op for OPEN/INVITE_ONLY, else 401
    guest / 403 non-member (members and invitees pass)."""
    if not await can_view_rosters(league, viewer, db):
        await require_league_read(league, viewer, db)


async def require_league_view(
    league_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> None:
    """Route dependency for any read keyed by league_id. A missing league
    passes through so the route's own 404 (or empty answer) is unchanged."""
    league = await db.get(League, league_id)
    if league is not None:
        await league_view_or_raise(league, viewer, db)


async def require_team_league_view(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> None:
    team = await db.get(Team, team_id)
    league = await db.get(League, team.league_id) if team is not None else None
    if league is not None:
        await league_view_or_raise(league, viewer, db)


async def require_draft_league_view(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> None:
    from app.models.draft import Draft

    draft = await db.get(Draft, draft_id)
    league = await db.get(League, draft.league_id) if draft is not None else None
    if league is not None:
        await league_view_or_raise(league, viewer, db)


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
