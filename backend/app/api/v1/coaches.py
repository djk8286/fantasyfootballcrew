from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.team import Team
from app.models.coach import Coach
from app.models.user import User
from app.schemas.coach import CoachCreate, CoachRead, CoachUpdate
from app.api.deps import get_current_user

router = APIRouter(tags=["coaches"])


async def _get_team(team_id: str, db: AsyncSession) -> Team:
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _require_team_owner(team: Team, current_user: User) -> None:
    if current_user.id not in {team.owner_id, team.co_owner_id}:
        raise HTTPException(status_code=403, detail="You do not own this team")


@router.post("/teams/{team_id}/coaches", response_model=CoachRead, status_code=201)
async def create_coach(
    team_id: str,
    data: CoachCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = await _get_team(team_id, db)
    _require_team_owner(team, current_user)

    coach = Coach(
        name=data.name,
        position=data.position,
        team_id=team_id,
        bonus_type=data.bonus_type,
        bonus_value=data.bonus_value,
    )
    db.add(coach)
    await db.commit()
    await db.refresh(coach)
    return coach


@router.get("/teams/{team_id}/coaches", response_model=list[CoachRead])
async def list_coaches(team_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Coach).where(Coach.team_id == team_id))
    return result.scalars().all()


@router.patch("/coaches/{coach_id}", response_model=CoachRead)
async def update_coach(
    coach_id: str,
    data: CoachUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Coach).where(Coach.id == coach_id))
    coach = result.scalar_one_or_none()
    if not coach:
        raise HTTPException(status_code=404, detail="Coach not found")

    team = await _get_team(coach.team_id, db)
    _require_team_owner(team, current_user)

    if data.name is not None:
        coach.name = data.name
    if data.position is not None:
        coach.position = data.position
    if data.bonus_type is not None:
        coach.bonus_type = data.bonus_type
    if data.bonus_value is not None:
        coach.bonus_value = data.bonus_value
    if data.is_active is not None:
        coach.is_active = data.is_active

    await db.commit()
    await db.refresh(coach)
    return coach


@router.delete("/coaches/{coach_id}", status_code=204)
async def delete_coach(
    coach_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Coach).where(Coach.id == coach_id))
    coach = result.scalar_one_or_none()
    if not coach:
        raise HTTPException(status_code=404, detail="Coach not found")

    team = await _get_team(coach.team_id, db)
    _require_team_owner(team, current_user)

    await db.delete(coach)
    await db.commit()
    return None
