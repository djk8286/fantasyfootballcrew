from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.league import League, LeagueType
from app.models.weekly_score import WeeklyScore
from app.models.user import User
from app.services.standings_service import (
    calculate_week,
    get_standings,
    get_combined_standings,
    get_weekly_matchups,
    get_season_schedule,
    DEFAULT_SEASON_WEEKS,
)
from app.services.guillotine_service import process_league_guillotine
from app.api.deps import get_current_user, require_commissioner

router = APIRouter(prefix="/leagues/{league_id}/standings", tags=["standings"])


@router.get("")
async def get_league_standings(
    league_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get current standings for a league.

    Returns team records (wins, losses, ties, points_for, points_against)
    computed from all weekly scores, ordered by wins descending.
    """
    # Verify league exists
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    standings = await get_standings(league_id, db)
    return {
        "league_id": league_id,
        "league_name": league.name,
        "league_type": league.league_type.value,
        "standings": standings,
    }


@router.get("/combined")
async def get_league_combined_standings(
    league_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Dual-Squad/Mirror (Phase 7) only -- each pair's two teams' records
    summed into one combined row. 404s for any other league_type rather
    than silently returning size-1 "pairs", since a caller building a
    combined-view UI needs to know definitively it doesn't apply."""
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    if league.league_type != LeagueType.DUAL_SQUAD:
        raise HTTPException(status_code=400, detail="Combined standings only apply to Dual-Squad leagues")

    combined = await get_combined_standings(league_id, db)
    return {"league_id": league_id, "league_name": league.name, "combined_standings": combined}


@router.get("/weekly")
async def get_weekly_scores(
    league_id: str,
    week: int = Query(..., ge=1, le=18, description="Week number (1-18)"),
    year: int = Query(..., ge=2020, le=2030, description="Season year"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all team scores for a specific week.

    Returns scores for each team and head-to-head matchups.
    """
    # Verify league exists
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    # Fetch weekly scores
    scores_result = await db.execute(
        select(WeeklyScore).where(
            WeeklyScore.league_id == league_id,
            WeeklyScore.week == week,
            WeeklyScore.year == year,
        )
    )
    scores = scores_result.scalars().all()

    # Get matchups
    matchups = await get_weekly_matchups(league_id, week, year, db)

    team_scores = [
        {
            "team_id": ws.team_id,
            "total_score": ws.total_score,
            "projected_score": ws.projected_score,
            "lineup_data": ws.lineup_data,
        }
        for ws in scores
    ]

    return {
        "league_id": league_id,
        "league_name": league.name,
        "week": week,
        "year": year,
        "team_scores": team_scores,
        "matchups": matchups,
    }


@router.get("/schedule")
async def get_season_schedule_endpoint(
    league_id: str,
    year: int = Query(..., ge=2020, le=2030, description="Season year"),
    weeks: int = Query(DEFAULT_SEASON_WEEKS, ge=1, le=18, description="Regular-season week count"),
    db: AsyncSession = Depends(get_db),
):
    """
    Full-season, week-by-week schedule. Weeks already calculated show real
    scores; future weeks show a simple projection (each team's own average
    from completed weeks so far -- see standings_service.get_season_schedule
    for why, and its limits).
    """
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    schedule = await get_season_schedule(league_id, year, db, num_weeks=weeks)
    return {
        "league_id": league_id,
        "league_name": league.name,
        "year": year,
        "schedule": schedule,
    }


@router.post("/calculate")
@limiter.limit("20/hour")
async def calculate_week_standings(
    request: Request,
    league_id: str,
    week: int = Query(..., ge=1, le=18, description="Week number (1-18)"),
    year: int = Query(..., ge=2020, le=2030, description="Season year"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Trigger weekly score calculation for all teams in a league.

    Iterates each team's roster, fetches stats (Sleeper API or DB),
    calculates fantasy points via the scoring engine, and stores
    WeeklyScore records.

    Commissioner only -- the docstring already said "intended for
    commissioner or system use" but nothing enforced it. Not called by
    the background scheduler (that only syncs player/stat data, never
    this), so there's no internal caller to account for here.
    """
    # Verify league exists
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    require_commissioner(league, current_user)

    try:
        result = await calculate_week(league_id, week, year, db)

        # Guillotine (Phase 4): the commissioner's manual trigger is a
        # second, independent entry point into elimination alongside the
        # scheduler's own once-per-week-transition hook (see scheduler.py)
        # -- process_league_guillotine is idempotent, so calling it here
        # too can't double-eliminate anyone even if both paths ever fire
        # for the same week.
        elimination = None
        if league.league_type == LeagueType.GUILLOTINE:
            elimination = await process_league_guillotine(league, year, week, db)

        return {
            "message": f"Calculated scores for week {week}, {year}",
            "result": result,
            "elimination": elimination,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calculation failed: {str(e)}")
