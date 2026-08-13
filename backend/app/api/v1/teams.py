from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.core.database import get_db
from app.models.team import Team
from app.models.league import League, LeagueType
from app.models.user import User
from app.schemas.team import TeamCreate, TeamRead, TeamUpdate
from app.api.deps import get_current_user, require_team_or_league_access, user_can_join_league
from pydantic import BaseModel

router = APIRouter(prefix="/teams", tags=["teams"])


async def _next_conference(league: League, league_id: str, db: AsyncSession) -> str | None:
    """Alternate A/B assignment for conference-type leagues, keeping the two
    sides balanced regardless of the order teams are added in. None for
    standard/two_man leagues, where conference is meaningless."""
    if league.league_type != LeagueType.CONFERENCE:
        return None
    result = await db.execute(select(Team).where(Team.league_id == league_id))
    existing = result.scalars().all()
    a_count = sum(1 for t in existing if t.conference == "A")
    b_count = sum(1 for t in existing if t.conference == "B")
    return "A" if a_count <= b_count else "B"


class BulkAddTeamsRequest(BaseModel):
    count: int = 1
    name_prefix: str = "CPU Team"


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(
    team_data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league_result = await db.execute(select(League).where(League.id == team_data.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    team = Team(
        name=team_data.name,
        owner_id=current_user.id,
        co_owner_id=team_data.co_owner_id,
        league_id=team_data.league_id,
        avatar_url=team_data.avatar_url,
        roster=[],
        conference=await _next_conference(league, team_data.league_id, db),
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
    """Update team name, avatar_url, co_owner_id, or conference. Owner,
    co-owner, or league commissioner only -- except conference, which is
    commissioner-only (letting owners self-assign could be used to dodge a
    tough conference)."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_team_or_league_access(team, league, current_user)

    if update_data.name is not None:
        team.name = update_data.name
    if update_data.avatar_url is not None:
        team.avatar_url = update_data.avatar_url
    if update_data.co_owner_id is not None:
        team.co_owner_id = update_data.co_owner_id
    if update_data.conference is not None:
        if current_user.id not in {league.commissioner_id, *(league.co_commissioner_ids or [])}:
            raise HTTPException(status_code=403, detail="Commissioner access required to change conference")
        if update_data.conference not in ("A", "B"):
            raise HTTPException(status_code=400, detail="conference must be 'A' or 'B'")
        team.conference = update_data.conference

    await db.commit()
    await db.refresh(team)
    return team


@router.post("/{team_id}/claim-co-owner", response_model=TeamRead)
async def claim_co_owner(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Self-service claim of the co-owner slot -- the second half of a
    2-Man Team. Mirrors claim_team's pattern (no invite link/email needed,
    just needs someone to know the team). Requires the slot to be open and
    the claimant not to already be the owner."""
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    # Visibility gate -- see user_can_join_league's docstring. Without
    # this, INVITE_ONLY/PRIVATE leagues were only "private" in the
    # discovery listing, not in who could actually claim a slot.
    if not await user_can_join_league(db, league, current_user):
        raise HTTPException(status_code=403, detail="You need an accepted invite or approved join request to join this league")

    if team.is_cpu:
        raise HTTPException(status_code=400, detail="Claim this team as owner first, not co-owner")
    if team.co_owner_id:
        raise HTTPException(status_code=400, detail="This team already has a co-owner")
    if current_user.id == team.owner_id:
        raise HTTPException(status_code=400, detail="You already own this team")

    team.co_owner_id = current_user.id
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

    league_result = await db.execute(select(League).where(League.id == team.league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if not await user_can_join_league(db, league, current_user):
        raise HTTPException(status_code=403, detail="You need an accepted invite or approved join request to join this league")

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

    # Track A/B balance locally rather than re-querying per team -- teams
    # created earlier in this same loop aren't committed yet, so a query
    # wouldn't see them.
    is_conference = league.league_type == LeagueType.CONFERENCE
    a_count = sum(1 for t in existing if t.conference == "A")
    b_count = sum(1 for t in existing if t.conference == "B")

    created = []
    for i in range(count):
        team_num = current_count + i + 1
        conference = None
        if is_conference:
            conference = "A" if a_count <= b_count else "B"
            if conference == "A":
                a_count += 1
            else:
                b_count += 1
        team = Team(
            name=f"{req.name_prefix} {team_num}",
            owner_id=None,
            league_id=league_id,
            roster=[],
            is_cpu=True,
            conference=conference,
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
