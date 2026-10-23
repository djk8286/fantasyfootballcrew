from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.league import League
from app.models.team import Team


async def lock_league_seats(db: AsyncSession, league_id: str, *teams: Team) -> None:
    """Serialize seat changes in a league (Postgres row lock, held to
    commit), then re-read the teams so checks see the winner's write."""
    await db.execute(select(League.id).where(League.id == league_id).with_for_update())
    for team in teams:
        await db.refresh(team)


SEAT_TAKEN = "You already manage a team in this league"
THEIR_SEAT_TAKEN = "That person already manages a team in this league"


async def require_one_live_seat(
    db: AsyncSession, league_id: str, user_id: str, detail: str = SEAT_TAKEN, joining: Team | None = None,
) -> None:
    """One live seat per person per league, checked under lock_league_seats.
    Holding two teams lets you answer your own trade offers. Joining your
    own Dual-Squad partner is the exception, and an eliminated team doesn't
    count (Guillotine: its manager may join a survivor). 409 on a clash."""
    query = select(Team.id).where(
        Team.league_id == league_id,
        Team.eliminated_week.is_(None),
        or_(Team.owner_id == user_id, Team.co_owner_id == user_id),
    )
    if joining is not None:
        query = query.where(Team.id != joining.id)
    partner = joining.partner_team_id if joining is not None else None
    if any(other_id != partner for other_id in (await db.execute(query)).scalars()):
        raise HTTPException(status_code=409, detail=detail)
