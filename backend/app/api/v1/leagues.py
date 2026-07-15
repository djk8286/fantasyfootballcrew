from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.user import User
from app.schemas.league import LeagueCreate, LeagueRead, LeagueUpdate
from app.services.scoring_engine import DEFAULT_SCORING
from app.api.deps import get_current_user, require_commissioner
from pydantic import BaseModel

router = APIRouter(prefix="/leagues", tags=["leagues"])


class ScoringConfigUpdate(BaseModel):
    scoring_config: dict


class CommissionerUpdate(BaseModel):
    action: str  # "add_co_commish", "remove_co_commish", "transfer"
    user_id: str


@router.post("", response_model=LeagueRead, status_code=status.HTTP_201_CREATED)
async def create_league(
    league_data: LeagueCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    league = League(
        name=league_data.name,
        description=league_data.description,
        commissioner_id=current_user.id,
        league_type=league_data.league_type,
        scoring_config=league_data.scoring_config or {},
        max_teams=league_data.max_teams,
        draft_type=league_data.draft_type,
        co_commissioner_ids=[],
    )
    db.add(league)
    await db.commit()
    await db.refresh(league)
    return league


@router.get("", response_model=list[LeagueRead])
async def list_leagues(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            League,
            func.count(Team.id).label("team_count")
        ).outerjoin(Team, Team.league_id == League.id)
        .group_by(League.id)
    )
    rows = result.all()
    leagues = []
    for league, team_count in rows:
        league_dict = LeagueRead.model_validate(league)
        league_dict.team_count = team_count
        leagues.append(league_dict)
    return leagues


# ─── Scoring Config (must be BEFORE /{league_id} to avoid greedy param) ─


@router.get("/{league_id}/scoring")
async def get_league_scoring(league_id: str, db: AsyncSession = Depends(get_db)):
    """Get the scoring config for a league, or return defaults."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    config = league.scoring_config if league.scoring_config else {}
    # Merge with defaults so missing keys are filled in
    merged = {**DEFAULT_SCORING}
    for category, rules in config.items():
        if isinstance(rules, dict) and category in merged:
            merged[category].update(rules)
        else:
            merged[category] = rules
    return merged


@router.put("/{league_id}/scoring")
async def update_league_scoring(
    league_id: str,
    data: ScoringConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the scoring config for a league."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)
    league.scoring_config = data.scoring_config
    await db.commit()
    return {"status": "ok", "scoring_config": league.scoring_config}


@router.patch("/{league_id}", response_model=LeagueRead)
async def update_league(
    league_id: str,
    update_data: LeagueUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update league settings (commissioner only)."""
    result = await db.execute(
        select(
            League,
            func.count(Team.id).label("team_count")
        ).outerjoin(Team, Team.league_id == League.id)
        .where(League.id == league_id)
        .group_by(League.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="League not found")
    league, team_count = row
    require_commissioner(league, current_user)

    if update_data.name is not None:
        league.name = update_data.name
    if update_data.description is not None:
        league.description = update_data.description
    if update_data.max_teams is not None:
        if update_data.max_teams < team_count:
            raise HTTPException(status_code=400, detail=f"Cannot reduce max teams below current count ({team_count})")
        league.max_teams = update_data.max_teams
    if update_data.draft_type is not None:
        league.draft_type = update_data.draft_type

    await db.commit()
    await db.refresh(league)
    league_dict = LeagueRead.model_validate(league)
    league_dict.team_count = team_count
    return league_dict


@router.post("/{league_id}/commissioner")
async def manage_commissioners(
    league_id: str,
    req: CommissionerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manage commissioner rights: add/remove co-commissioners, transfer ownership. Owner only."""
    result = await db.execute(select(League).where(League.id == league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if current_user.id != league.commissioner_id:
        raise HTTPException(status_code=403, detail="Only the league owner can manage commissioner rights")

    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == req.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Ensure co_commissioner_ids is initialized
    if league.co_commissioner_ids is None:
        league.co_commissioner_ids = []

    if req.action == "add_co_commish":
        if req.user_id == league.commissioner_id:
            raise HTTPException(status_code=400, detail="Commissioner is already the league owner")
        if req.user_id in league.co_commissioner_ids:
            raise HTTPException(status_code=400, detail="User is already a co-commissioner")
        league.co_commissioner_ids.append(req.user_id)

    elif req.action == "remove_co_commish":
        if req.user_id not in league.co_commissioner_ids:
            raise HTTPException(status_code=400, detail="User is not a co-commissioner")
        league.co_commissioner_ids.remove(req.user_id)

    elif req.action == "transfer":
        if req.user_id == league.commissioner_id:
            raise HTTPException(status_code=400, detail="Already the commissioner")
        # Make target the commissioner, current becomes co-commissioner
        old_commish = league.commissioner_id
        league.commissioner_id = req.user_id
        if old_commish not in league.co_commissioner_ids:
            league.co_commissioner_ids.append(old_commish)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    await db.commit()
    await db.refresh(league)
    return {
        "commissioner_id": league.commissioner_id,
        "co_commissioner_ids": league.co_commissioner_ids or [],
    }


@router.get("/{league_id}", response_model=LeagueRead)
async def get_league(league_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            League,
            func.count(Team.id).label("team_count")
        ).outerjoin(Team, Team.league_id == League.id)
        .where(League.id == league_id)
        .group_by(League.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="League not found")
    league, team_count = row
    league_dict = LeagueRead.model_validate(league)
    league_dict.team_count = team_count
    return league_dict
