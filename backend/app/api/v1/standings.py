from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.league import League
from app.models.weekly_score import WeeklyScore
from app.services.standings_service import (
    calculate_week,
    get_standings,
    get_weekly_matchups,
)

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
        "standings": standings,
    }


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


@router.post("/calculate")
async def calculate_week_standings(
    league_id: str,
    week: int = Query(..., ge=1, le=18, description="Week number (1-18)"),
    year: int = Query(..., ge=2020, le=2030, description="Season year"),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger weekly score calculation for all teams in a league.

    Iterates each team's roster, fetches stats (Sleeper API or DB),
    calculates fantasy points via the scoring engine, and stores
    WeeklyScore records.

    Intended for commissioner or system use.
    """
    # Verify league exists
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    try:
        result = await calculate_week(league_id, week, year, db)
        return {
            "message": f"Calculated scores for week {week}, {year}",
            "result": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calculation failed: {str(e)}")
