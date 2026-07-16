from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.core.database import get_db
from app.models.team import Team
from app.models.league import League
from app.models.user import User
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate
from app.api.deps import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/teams", tags=["teams"])


class BulkAddTeamsRequest(BaseModel):
    count: int = 1
    name_prefix: str = "CPU Team"


class CommissionerActionRequest(BaseModel):
    action: str  # "add_co_commish", "remove_co_commish", "transfer"
    user_id: str


def _require_team_or_league_access(team: Team, league: League, current_user: User) -> None:
    allowed_ids = {team.owner_id, team.co_owner_id, league.commissioner_id, *(league.co_commissioner_ids or [])}
    if current_user.id not in allowed_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this team")


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(
    team_data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = Team(
        name=team_data.name,
        owner_id=current_user.id,
        co_owner_id=team_data.co_owner_id,
        league_id=team_data.league_id,
        avatar_url=team_data.avatar_url,
        roster=[],
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


@router.patch("/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: str,
    update_data: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update team name, avatar_url, or co_owner_id. Owner, co-owner, or league commissioner only."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    _require_team_or_league_access(team, league, current_user)

    if update_data.name is not None:
        team.name = update_data.name
    if update_data.avatar_url is not None:
        team.avatar_url = update_data.avatar_url
    if update_data.co_owner_id is not None:
        team.co_owner_id = update_data.co_owner_id

    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/claim", response_model=TeamRead)
async def claim_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Claim a CPU team as the authenticated user."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if not team.is_cpu:
        raise HTTPException(status_code=400, detail="Team is already owned by a user")

    team.owner_id = current_user.id
    team.is_cpu = False
    await db.commit()
    await db.refresh(team)
    return team


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a team (league commissioner only)."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if current_user.id not in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        raise HTTPException(status_code=403, detail="Commissioner access required")

    await db.delete(team)
    await db.commit()
    return None


@router.post("/bulk-add/{league_id}", status_code=status.HTTP_201_CREATED)
async def bulk_add_cpu_teams(
    league_id: str,
    req: BulkAddTeamsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fill a league's empty slots with CPU-controlled teams (commissioner only)."""
    # Check league exists and get current team count
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if current_user.id not in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
        raise HTTPException(status_code=403, detail="Commissioner access required")

    result = await db.execute(select(Team).where(Team.league_id == league_id))
    existing = result.scalars().all()
    current_count = len(existing)
    max_teams = league.max_teams or 32
    available_slots = max_teams - current_count

    if available_slots <= 0:
        raise HTTPException(status_code=400, detail=f"League is full ({current_count}/{max_teams})")

    count = min(req.count, available_slots)

    created = []
    for i in range(count):
        team_num = current_count + i + 1
        team = Team(
            name=f"{req.name_prefix} {team_num}",
            owner_id=None,
            league_id=league_id,
            roster=[],
            is_cpu=True,
        )
        db.add(team)
        created.append(team)

    await db.commit()
    for t in created:
        await db.refresh(t)

    return {
        "message": f"Added {len(created)} CPU teams",
        "teams": [{"id": t.id, "name": t.name, "is_cpu": t.is_cpu} for t in created],
        "total_teams": current_count + len(created),
        "max_teams": max_teams,
    }


@router.get("/league/{league_id}", response_model=list[TeamRead])
async def get_league_teams(league_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.league_id == league_id))
    teams = result.scalars().all()
    return teams


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(team_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team
