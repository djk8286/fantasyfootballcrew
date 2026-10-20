"""Read endpoints for the team page and league feeds:
GET /teams/{id}/roster and GET /leagues/{id}/activity."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional
from app.api.v1.lineups import (
    _current_lineup,
    _get_team_league_or_404,
    _player_states,
    _resolve_roster,
    _serialize_roster_player,
    load_week_games,
)
from app.core.database import get_db
from app.models.league import League
from app.models.team import Team
from app.models.user import User
from app.services.lineup_slots import lineup_issues
from app.services.season_weeks import league_start_week
from app.services.team_activity_service import league_activity, team_record

router = APIRouter(tags=["team-hub"])


async def _usernames(ids: list[str | None], db: AsyncSession) -> dict[str, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


@router.get("/teams/{team_id}/roster")
async def get_team_roster(
    team_id: str,
    week: int = Query(..., ge=1, le=18),
    year: int = Query(..., ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
):
    """One call for the team page: the team with owner usernames, its
    record from standings (Team.points_for is never written), the league's
    first week, and the roster rows GET /lineup returns, each with the
    slot he fills this week ("BN" on the bench)."""
    team, league = await _get_team_league_or_404(team_id, db)
    teams = (await db.execute(select(Team).where(Team.league_id == league.id))).scalars().all()
    roster = await _resolve_roster(team, db)
    games = await load_week_games(year, week, db)
    current = await _current_lineup(team, league, roster, week, year, db)
    slot_of = {e["player_id"]: e["slot"] for e in current.slots if e.get("player_id")}
    scoring = league.scoring_config or {}
    names = await _usernames([team.owner_id, team.co_owner_id], db)

    rows = []
    for p in roster:
        row = _serialize_roster_player(p, p.id in slot_of, scoring, games, week, year)
        row["slot"] = slot_of.get(p.id, "BN")
        rows.append(row)

    return {
        "team": {
            "id": team.id,
            "name": team.name,
            "league_id": league.id,
            "avatar_url": team.avatar_url,
            "is_cpu": team.is_cpu,
            "owner_id": team.owner_id,
            "co_owner_id": team.co_owner_id,
            "owner_username": names.get(team.owner_id or ""),
            "co_owner_username": names.get(team.co_owner_id or ""),
        },
        "record": await team_record(league, team, list(teams), db),
        "week": week,
        "year": year,
        "league_start_week": await league_start_week(league.id, year, db),
        "has_lineup_set": current.has_lineup_set,
        "slots": current.slots,
        "issues": lineup_issues(current.slots, _player_states(roster, games), current.unplaced),
        "roster": rows,
    }


@router.get("/leagues/{league_id}/activity")
async def get_league_activity(
    league_id: str,
    team_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
):
    """League feed, newest first: finished trades, waiver adds, the draft
    and weekly results, with team and player names resolved. team_id
    narrows it to one team. Pending and declined moves only appear for the
    managers of a team involved; cancel is set on the viewer's own pending
    ones (POST .../trades/{id}/cancel or DELETE .../waivers/claims/{id})."""
    league = (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none()
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    teams = (await db.execute(select(Team).where(Team.league_id == league_id))).scalars().all()
    if team_id and team_id not in {t.id for t in teams}:
        raise HTTPException(status_code=404, detail="Team not found in this league")
    items = await league_activity(league, list(teams), db, viewer_id=viewer.id if viewer else None,
                                  team_id=team_id, limit=limit)
    return {"league_id": league_id, "items": items}
