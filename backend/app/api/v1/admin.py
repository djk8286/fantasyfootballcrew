"""
Read-only dev/management dashboard for David and anyone he grants
is_admin to (see User.is_admin, deps.require_admin). Deliberately
read-only -- no delete/edit endpoints here. The 2026-09-08 incident this
exists to prevent wasn't a bad delete so much as a delete made without
knowing who was actually using the app; the fix for that is visibility,
not a more convenient delete button. Destructive league/user cleanup
stays a deliberate one-off script against prod, same as it's always
been -- see [[ffc-beta-draft-readiness]] in project memory.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.user import User
from app.models.league import League
from app.models.team import Team
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.api.deps import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Top-line counts -- the "is this actually just me testing" check
    that would have caught the 2026-09-08 incident before it happened."""
    users = (await db.execute(select(func.count(User.id)))).scalar()
    leagues = (await db.execute(select(func.count(League.id)))).scalar()
    teams = (await db.execute(select(func.count(Team.id)))).scalar()
    drafts_in_progress = (
        await db.execute(select(func.count(Draft.id)).where(Draft.status == DraftRunStatus.IN_PROGRESS))
    ).scalar()
    picks_made = (await db.execute(select(func.count(DraftPick.id)))).scalar()
    return {
        "users": users,
        "leagues": leagues,
        "teams": teams,
        "drafts_in_progress": drafts_in_progress,
        "draft_picks_made": picks_made,
    }


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Every account, newest first. Includes email -- this endpoint is
    already admin-gated, unlike the public-facing UserPublic schema
    (GET /users/{id}) that deliberately withholds it."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "provider": u.provider,
            "email_verified": u.email_verified,
            "is_admin": u.is_admin,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.get("/leagues")
async def list_leagues(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Every league, newest first, with who commissions it -- the exact
    "who do I even contact" question that was unanswerable during the
    2026-09-08 wipe. Team.league relationship is lazy="selectin" (see
    League model), so `l.teams` below is already loaded, not an N+1."""
    leagues_result = await db.execute(select(League).order_by(League.created_at.desc()))
    leagues = leagues_result.scalars().all()

    commissioner_ids = {l.commissioner_id for l in leagues}
    users_by_id: dict[str, User] = {}
    if commissioner_ids:
        users_result = await db.execute(select(User).where(User.id.in_(commissioner_ids)))
        users_by_id = {u.id: u for u in users_result.scalars().all()}

    return [
        {
            "id": l.id,
            "name": l.name,
            "commissioner_username": users_by_id[l.commissioner_id].username if l.commissioner_id in users_by_id else None,
            "commissioner_email": users_by_id[l.commissioner_id].email if l.commissioner_id in users_by_id else None,
            "league_type": l.league_type.value,
            "visibility": l.visibility.value,
            "draft_status": l.draft_status.value,
            "team_count": len(l.teams),
            "is_mock": l.is_mock,
            "created_at": l.created_at,
        }
        for l in leagues
    ]
