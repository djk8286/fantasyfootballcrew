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


async def require_one_live_seat(db: AsyncSession, team: Team, user_id: str, detail: str) -> None:
    """One live seat per person per league before they take a seat on
    `team`. Holding two teams lets you answer your own trade offers. A
    Dual-Squad partner is the exception, and so is an eliminated team
    (Guillotine: its manager may join a survivor)."""
    other_teams = await db.execute(
        select(Team.id).where(
            Team.league_id == team.league_id,
            Team.id != team.id,
            Team.eliminated_week.is_(None),
            or_(Team.owner_id == user_id, Team.co_owner_id == user_id),
        )
    )
    if any(other_id != team.partner_team_id for other_id in other_teams.scalars()):
        raise HTTPException(status_code=400, detail=detail)
