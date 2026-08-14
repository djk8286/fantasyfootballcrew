from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.team import Team
from app.models.league import League
from app.models.player import Player
from app.models.lineup import Lineup
from app.models.weekly_score import WeeklyScore
from app.models.user import User
from app.api.deps import get_current_user, require_team_or_league_access
from app.services.scoring_engine import calculate_player_score, calculate_optimal_lineup, DEFAULT_ROSTER_SLOTS
from app.services.sleeper_sync import sleeper_avatar_url, effective_season_stats
from app.services.best_ball_service import get_best_ball_settings

router = APIRouter(prefix="/teams", tags=["lineups"])


async def _get_team_league_or_404(team_id: str, db: AsyncSession) -> tuple[Team, League]:
    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    result = await db.execute(select(League).where(League.id == team.league_id))
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(status_code=404, detail="League not found")
    return team, league


async def _resolve_roster(team: Team, db: AsyncSession) -> list[Player]:
    if not team.roster:
        return []
    result = await db.execute(select(Player).where(Player.id.in_(team.roster)))
    players_by_id = {p.id: p for p in result.scalars().all()}
    # Preserve team.roster's own order rather than the query's -- keeps the
    # lineup UI stable/predictable between loads instead of reshuffling to
    # whatever order the DB happens to return.
    return [players_by_id[pid] for pid in team.roster if pid in players_by_id]


def _serialize_roster_player(player: Player, is_starter: bool, scoring_config: dict) -> dict:
    stats, year = effective_season_stats(player)
    return {
        "id": player.id,
        "full_name": f"{player.first_name} {player.last_name}",
        "position": player.position,
        "team": player.team or "FA",
        "injury_status": player.injury_status,
        "bye_week": player.bye_week,
        "avatar_url": sleeper_avatar_url(player.sleeper_id),
        "season_points": calculate_player_score(stats, scoring_config, player.position),
        "season_points_year": year,
        "is_starter": is_starter,
    }


@router.get("/{team_id}/lineup")
async def get_lineup(
    team_id: str,
    week: int = Query(..., ge=1, le=18),
    year: int = Query(..., ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
):
    """A team's roster for (week, year), each player flagged is_starter or
    not. No Lineup row for this (team, week, year) yet -- has_lineup_set:
    false, every player comes back as bench (not "started as a mistake") --
    the frontend/scoring both treat "never touched this" as "score the
    whole roster" (see standings_service.calculate_week), not as an empty
    lineup, so this endpoint's shape shouldn't imply otherwise.

    Best-Ball (Phase 6): there is no manual starter selection at all in
    this mode -- starters come from that week's WeeklyScore.lineup_data
    (auto_starters, set by calculate_week's own optimizer call), not any
    Lineup row. No WeeklyScore yet for this week (scoring hasn't run) ->
    every player comes back as bench, same "nothing decided yet" shape
    the non-best-ball no-Lineup-row case already uses."""
    team, league = await _get_team_league_or_404(team_id, db)
    roster_slots = dict(DEFAULT_ROSTER_SLOTS)
    roster_slots.update(league.roster_slots or {})
    scoring_config = league.scoring_config or {}
    is_best_ball = get_best_ball_settings(league)["enabled"]

    if is_best_ball:
        ws_result = await db.execute(
            select(WeeklyScore).where(
                WeeklyScore.team_id == team_id, WeeklyScore.week == week, WeeklyScore.year == year,
            )
        )
        weekly_score = ws_result.scalar_one_or_none()
        starter_ids = set((weekly_score.lineup_data or {}).get("auto_starters") or []) if weekly_score else set()
        has_lineup_set = weekly_score is not None and bool(starter_ids)
    else:
        result = await db.execute(
            select(Lineup).where(Lineup.team_id == team_id, Lineup.week == week, Lineup.year == year)
        )
        lineup = result.scalar_one_or_none()
        starter_ids = set(lineup.starters or []) if lineup else set()
        has_lineup_set = lineup is not None

    roster = await _resolve_roster(team, db)
    return {
        "team_id": team_id,
        "week": week,
        "year": year,
        "roster_slots": roster_slots,
        "best_ball": is_best_ball,
        "has_lineup_set": has_lineup_set,
        "starters": sorted(starter_ids),
        "roster": [_serialize_roster_player(p, p.id in starter_ids, scoring_config) for p in roster],
    }


class SetLineupRequest(BaseModel):
    starters: list[str]


@router.put("/{team_id}/lineup")
@limiter.limit("60/hour")  # generous -- managers legitimately tweak a lineup multiple times before games lock
async def set_lineup(
    request: Request,
    team_id: str,
    week: int = Query(..., ge=1, le=18),
    year: int = Query(..., ge=2020, le=2030),
    data: SetLineupRequest = ...,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team, league = await _get_team_league_or_404(team_id, db)
    require_team_or_league_access(team, league, current_user)
    if get_best_ball_settings(league)["enabled"]:
        raise HTTPException(
            status_code=400,
            detail="This league uses Best-Ball auto-lineups -- starters are selected automatically each week.",
        )

    roster_set = set(team.roster or [])
    starters = list(dict.fromkeys(data.starters))  # de-dupe, preserve order
    invalid = [pid for pid in starters if pid not in roster_set]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Not on this team's roster: {invalid}")

    roster_slots = dict(DEFAULT_ROSTER_SLOTS)
    roster_slots.update(league.roster_slots or {})
    total_slots = sum(roster_slots.values())
    if len(starters) > total_slots:
        raise HTTPException(
            status_code=422,
            detail=f"Too many starters: {len(starters)} submitted, this league only has {total_slots} starting slots",
        )

    result = await db.execute(
        select(Lineup).where(Lineup.team_id == team_id, Lineup.week == week, Lineup.year == year)
    )
    lineup = result.scalar_one_or_none()
    if lineup:
        lineup.starters = starters
    else:
        db.add(Lineup(team_id=team_id, week=week, year=year, starters=starters))
    await db.commit()
    return {"status": "ok", "starters": starters}


@router.post("/{team_id}/lineup/optimize")
@limiter.limit("30/hour")
async def optimize_lineup(
    request: Request,
    team_id: str,
    week: int = Query(..., ge=1, le=18),
    year: int = Query(..., ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-fill this week's lineup with the best starters available,
    ranked by effective_season_stats (current-season live production if
    the season's started and synced anything, else last season's archived
    total -- the same "best real number available" this app already uses
    for season_points/projected_points, not a game-by-game projection this
    app has no data source for). Saves the result, same as a manual set."""
    team, league = await _get_team_league_or_404(team_id, db)
    require_team_or_league_access(team, league, current_user)
    if get_best_ball_settings(league)["enabled"]:
        raise HTTPException(
            status_code=400,
            detail="This league uses Best-Ball auto-lineups -- starters are selected automatically each week.",
        )

    roster_slots = dict(DEFAULT_ROSTER_SLOTS)
    roster_slots.update(league.roster_slots or {})
    scoring_config = league.scoring_config or {}

    roster = await _resolve_roster(team, db)
    roster_for_optimizer = {}
    for p in roster:
        stats, _ = effective_season_stats(p)
        roster_for_optimizer[p.id] = {"stats": stats, "position": p.position, "name": f"{p.first_name} {p.last_name}"}

    result = calculate_optimal_lineup(
        roster_for_optimizer,
        scoring_config,
        n_qb=roster_slots.get("QB", 0),
        n_rb=roster_slots.get("RB", 0),
        n_wr=roster_slots.get("WR", 0),
        n_te=roster_slots.get("TE", 0),
        n_flex=roster_slots.get("FLEX", 0),
        n_superflex=roster_slots.get("SUPERFLEX", 0),
        n_k=roster_slots.get("K", 0),
        n_def=roster_slots.get("DEF", 0),
        n_dl=roster_slots.get("DL", 0),
        n_lb=roster_slots.get("LB", 0),
        n_db=roster_slots.get("DB", 0),
        n_idp_flex=roster_slots.get("IDP_FLEX", 0),
    )
    starters = [a["player_id"] for a in result["lineup"]]

    lu_result = await db.execute(
        select(Lineup).where(Lineup.team_id == team_id, Lineup.week == week, Lineup.year == year)
    )
    lineup = lu_result.scalar_one_or_none()
    if lineup:
        lineup.starters = starters
    else:
        db.add(Lineup(team_id=team_id, week=week, year=year, starters=starters))
    await db.commit()
    return {"status": "ok", "starters": starters, "optimal_score": result["optimal_score"]}
