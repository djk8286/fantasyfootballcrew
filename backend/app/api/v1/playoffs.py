from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.playoff import Playoff, PlayoffMatchup
from app.services.playoff_service import get_playoff_settings

router = APIRouter(prefix="/leagues/{league_id}/playoffs", tags=["playoffs"])


def _team_ref(team_id: str | None, teams_by_id: dict[str, Team]) -> dict | None:
    if not team_id:
        return None
    team = teams_by_id.get(team_id)
    return {"id": team_id, "name": team.name if team else "Unknown"}


@router.get("")
async def get_playoffs(league_id: str, year: int | None = None, db: AsyncSession = Depends(get_db)):
    """Current playoff bracket for a league, or a "not started yet" shape
    with just the settings if nothing's been generated (either playoffs
    are disabled, or the regular season isn't over yet). year defaults
    to the most recently created bracket, mirroring how draft/standings
    endpoints default to "whatever's current" rather than forcing every
    caller to know the year up front."""
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")

    settings = get_playoff_settings(league)

    query = select(Playoff).where(Playoff.league_id == league_id)
    if year is not None:
        query = query.where(Playoff.year == year)
    query = query.order_by(Playoff.year.desc())
    result = await db.execute(query)
    playoff = result.scalars().first()

    if not playoff:
        return {
            "has_bracket": False,
            "settings": settings,
        }

    matchups_result = await db.execute(
        select(PlayoffMatchup).where(PlayoffMatchup.playoff_id == playoff.id).order_by(
            PlayoffMatchup.round, PlayoffMatchup.bracket, PlayoffMatchup.slot
        )
    )
    matchups = matchups_result.scalars().all()

    team_ids = {tid for m in matchups for tid in (m.team_a_id, m.team_b_id, m.winner_team_id) if tid}
    teams_result = await db.execute(select(Team).where(Team.id.in_(team_ids))) if team_ids else None
    teams_by_id = {t.id: t for t in teams_result.scalars().all()} if teams_result else {}

    # Attach team names to the frozen seed snapshot too, for display.
    seeds_with_names = {}
    for bracket_label, entries in (playoff.seeds or {}).items():
        seeds_with_names[bracket_label] = [
            {**e, "team_name": teams_by_id.get(e["team_id"]).name if teams_by_id.get(e["team_id"]) else "Unknown"}
            for e in entries
        ]

    return {
        "has_bracket": True,
        "settings": settings,
        "year": playoff.year,
        "status": playoff.status.value,
        "seeding_method": playoff.seeding_method,
        "conference_bracket_mode": playoff.conference_bracket_mode,
        "start_week": playoff.start_week,
        "total_rounds": playoff.total_rounds,
        "current_round": playoff.current_round,
        "seeds": seeds_with_names,
        "matchups": [
            {
                "id": m.id,
                "bracket": m.bracket,
                "round": m.round,
                "slot": m.slot,
                "week": m.week,
                "team_a": _team_ref(m.team_a_id, teams_by_id),
                "team_b": _team_ref(m.team_b_id, teams_by_id),
                "is_bye": m.is_bye,
                "winner_team_id": m.winner_team_id,
            }
            for m in matchups
        ],
    }
