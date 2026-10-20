from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dataclasses import dataclass
from pydantic import BaseModel
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.team import Team
from app.models.league import League
from app.models.player import Player
from app.models.lineup import Lineup
from app.models.weekly_score import WeeklyScore
from app.models.user import User
from app.api.deps import get_current_user, require_league_read, require_team_or_league_access
from app.services.scoring_engine import calculate_player_score, calculate_optimal_lineup, DEFAULT_ROSTER_SLOTS
from app.services.sleeper_sync import sleeper_avatar_url, effective_season_stats
from app.services.best_ball_service import get_best_ball_settings
from app.services.default_lineup import (
    candidate_from_player,
    choose_default_starters,
    is_inactive_status,
)
from app.services.standings_service import week_schedule_state
from app.services.lineup_slots import (
    LineupError,
    PlayerState,
    Slots,
    expand_slots,
    lineup_issues,
    place_starters,
    starters_of,
    validate_slots,
)
from app.services.nfl_schedule_service import as_utc, ensure_week_games, game_started, game_teams
from app.models.nfl_game import NFLGame
from app.core.config import settings
from app.services.nfl_projections_service import load_projections, projected_points
from app.services.standings_service import _effective_matchups
from datetime import datetime, timezone

router = APIRouter(prefix="/teams", tags=["lineups"])

def _is_inactive(player: Player) -> bool:
    return is_inactive_status(player.injury_status)


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


class WeekGames:
    """The NFL week's games keyed by Player.team code. known is False when
    no games are synced, and then nobody is on bye."""

    def __init__(self, games: list[NFLGame], now: datetime):
        self.known = bool(games)
        self.now = now
        self.by_team: dict[str, NFLGame] = {code: g for g in games for code in game_teams(g)}

    def on_bye(self, nfl_team: str | None) -> bool:
        return self.known and bool(nfl_team) and nfl_team not in self.by_team

    def locked(self, nfl_team: str | None) -> bool:
        game = self.by_team.get(nfl_team or "")
        return bool(game) and game_started(game, self.now)

    def info(self, nfl_team: str | None) -> dict | None:
        game = self.by_team.get(nfl_team or "")
        if not game:
            return None
        home, away = game_teams(game)
        is_home = home == nfl_team
        return {
            "opponent": away if is_home else home,
            "home": is_home,
            "kickoff_at": as_utc(game.kickoff_at).isoformat(),
            "status": game.status_state,
            "detail": game.status_detail,
            "locked": game_started(game, self.now),
        }


async def load_week_games(year: int, week: int, db: AsyncSession) -> WeekGames:
    return WeekGames(await ensure_week_games(year, week, 2, db), datetime.now(timezone.utc))


def _last_week_points(player: Player, week: int, year: int, scoring_config: dict) -> float | None:
    """Points in week - 1 of this season, or None if he has no stat line for it."""
    if week <= 1 or player.stats_year != year:
        return None
    stats = (player.week_stats or {}).get(str(week - 1))
    return None if stats is None else calculate_player_score(stats, scoring_config, player.position)


async def week_projections(roster: list[Player], year: int, week: int, db: AsyncSession) -> dict[str, dict] | None:
    """Projected stat lines for these players, or None when projections
    are switched off or none are synced for the week at all."""
    if not settings.SLEEPER_PROJECTIONS_ENABLED:
        return None
    return await load_projections(db, [p.id for p in roster], year, week) or None


def _projected(player: Player, projections: dict | None, games: WeekGames, scoring_config: dict) -> float | None:
    """League-scored projection. A player on bye projects 0. Unprojected
    players get None while the week has projections at all."""
    if projections is None:
        return None
    if games.on_bye(player.team):
        return 0.0
    return projected_points(projections.get(player.id), scoring_config, player.position)


def projected_total(slots: Slots, by_id: dict[str, Player], projections: dict | None,
                    games: WeekGames, scoring_config: dict) -> float | None:
    if projections is None:
        return None
    return round(sum(
        _projected(by_id[e["player_id"]], projections, games, scoring_config) or 0.0
        for e in slots if e.get("player_id") in by_id
    ), 2)


def _serialize_roster_player(
    player: Player, is_starter: bool, scoring_config: dict, games: WeekGames, week: int, year: int,
    projections: dict | None = None,
) -> dict:
    stats, stats_year = effective_season_stats(player)
    return {
        "id": player.id,
        "full_name": f"{player.first_name} {player.last_name}",
        "position": player.position,
        "team": player.team or "FA",
        "injury_status": player.injury_status,
        "bye_week": player.bye_week,
        "avatar_url": sleeper_avatar_url(player.sleeper_id),
        "season_points": calculate_player_score(stats, scoring_config, player.position),
        "season_points_year": stats_year,
        "last_week_points": _last_week_points(player, week, year, scoring_config),
        "projected_points": _projected(player, projections, games, scoring_config),
        "game": games.info(player.team),
        "on_bye": games.on_bye(player.team),
        "is_starter": is_starter,
    }


@dataclass
class CurrentLineup:
    """What a team will score for a week right now, placed into slots."""
    has_lineup_set: bool
    starters: list[str]
    slots: Slots
    unplaced: list[str]
    default_starters: list[str]


def _league_slot_settings(league: League) -> dict:
    roster_slots = dict(DEFAULT_ROSTER_SLOTS)
    roster_slots.update(league.roster_slots or {})
    return roster_slots


async def _current_lineup(
    team: Team, league: League, roster: list[Player], week: int, year: int, db: AsyncSession,
) -> CurrentLineup:
    """The saved Lineup if there is one, otherwise the default lineup
    calculate_week scores (frozen in that week's WeeklyScore once the week
    has started). Best-ball leagues use that week's auto_starters."""
    roster_slots = _league_slot_settings(league)
    positions = {p.id: p.position for p in roster}

    if get_best_ball_settings(league)["enabled"]:
        ws = (await db.execute(select(WeeklyScore).where(
            WeeklyScore.team_id == team.id, WeeklyScore.week == week, WeeklyScore.year == year,
        ))).scalar_one_or_none()
        auto = [pid for pid in ((ws.lineup_data or {}).get("auto_starters") or []) if pid in positions] if ws else []
        slots, unplaced = place_starters(auto, positions, roster_slots)
        return CurrentLineup(bool(auto), auto, slots, unplaced, [])

    lineup = (await db.execute(
        select(Lineup).where(Lineup.team_id == team.id, Lineup.week == week, Lineup.year == year)
    )).scalar_one_or_none()
    if lineup is not None:
        starters = [pid for pid in (lineup.starters or []) if pid in positions]
        stored = [e for e in (lineup.slots or []) if e.get("player_id") in positions]
        try:
            # Stored slots can go stale if the commissioner changes slot
            # counts mid-week; then fall back to placing the starters again.
            if not stored:
                raise LineupError("no stored slots")
            slots, unplaced = validate_slots(stored, positions, {}, roster_slots), []
        except LineupError:
            slots, unplaced = place_starters(starters, positions, roster_slots)
        return CurrentLineup(True, starters, slots, unplaced, [])

    teams_playing, week_started, week_final = await week_schedule_state(year, week, db, with_final=True)
    ws = (await db.execute(select(WeeklyScore).where(
        WeeklyScore.team_id == team.id, WeeklyScore.week == week, WeeklyScore.year == year,
    ))).scalar_one_or_none()
    data = (ws.lineup_data or {}) if ws else {}
    frozen = data.get("default_starters") if data.get("lineup_source") == "default" else None
    if week_started and frozen is not None:
        default_starters = [pid for pid in frozen if pid in positions]
    else:
        default_starters = choose_default_starters(
            [candidate_from_player(p, week, year) for p in roster],
            roster_slots, league.scoring_config or {},
            teams_playing=teams_playing, exclude_inactive=not week_final,
        )
    slots, unplaced = place_starters(default_starters, positions, roster_slots)
    return CurrentLineup(False, default_starters, slots, unplaced, default_starters)


def _player_states(roster: list[Player], games: WeekGames) -> dict[str, PlayerState]:
    return {
        p.id: PlayerState(
            name=f"{p.first_name} {p.last_name}",
            injury_status=p.injury_status,
            inactive=_is_inactive(p),
            on_bye=games.on_bye(p.team),
        )
        for p in roster
    }


def _run_optimizer(pool: dict, scoring_config: dict, counts: dict) -> dict:
    return calculate_optimal_lineup(
        pool,
        scoring_config,
        n_qb=counts.get("QB", 0),
        n_rb=counts.get("RB", 0),
        n_wr=counts.get("WR", 0),
        n_te=counts.get("TE", 0),
        n_flex=counts.get("FLEX", 0),
        n_superflex=counts.get("SUPERFLEX", 0),
        n_k=counts.get("K", 0),
        n_def=counts.get("DEF", 0),
        n_dl=counts.get("DL", 0),
        n_lb=counts.get("LB", 0),
        n_db=counts.get("DB", 0),
        n_idp_flex=counts.get("IDP_FLEX", 0),
    )


async def _save(team_id: str, week: int, year: int, slots: Slots, db: AsyncSession) -> list[str]:
    starters = starters_of(slots)
    lineup = (await db.execute(
        select(Lineup).where(Lineup.team_id == team_id, Lineup.week == week, Lineup.year == year)
    )).scalar_one_or_none()
    if lineup:
        lineup.starters = starters
        lineup.slots = slots
    else:
        db.add(Lineup(team_id=team_id, week=week, year=year, starters=starters, slots=slots))
    await db.commit()
    return starters


@router.get("/{team_id}/lineup")
async def get_lineup(
    team_id: str,
    week: int = Query(..., ge=1, le=18),
    year: int = Query(..., ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A team's roster for (week, year) with each player's game, and the
    lineup that scores right now placed into the league's slots.

    slots: [{"slot", "player_id"}] in league order; null player_id is an
    empty slot. No saved Lineup -> has_lineup_set false, and slots hold
    the default lineup calculate_week will score (default_starters).
    issues lists what will cost points: empty slots, starters ruled out or
    on bye, and starters from an old lineup that fit no slot (unplaced).
    starters/is_starter only reflect a saved lineup (or best-ball's
    auto_starters), same as before slots existed."""
    team, league = await _get_team_league_or_404(team_id, db)
    # Login required; PRIVATE leagues only for members (see require_league_read).
    await require_league_read(league, current_user, db)
    roster_slots = _league_slot_settings(league)
    scoring_config = league.scoring_config or {}
    is_best_ball = get_best_ball_settings(league)["enabled"]

    roster = await _resolve_roster(team, db)
    games = await load_week_games(year, week, db)
    current = await _current_lineup(team, league, roster, week, year, db)
    starter_ids = set(current.starters) if current.has_lineup_set else set()
    projections = await week_projections(roster, year, week, db)
    by_id = {p.id: p for p in roster}
    return {
        "team_id": team_id,
        "week": week,
        "year": year,
        "roster_slots": roster_slots,
        "best_ball": is_best_ball,
        "has_lineup_set": current.has_lineup_set,
        "default_starters": current.default_starters,
        "schedule_known": games.known,
        "starters": sorted(starter_ids),
        "slots": current.slots,
        "unplaced": current.unplaced,
        "issues": lineup_issues(current.slots, _player_states(roster, games), current.unplaced),
        "projected_total": projected_total(current.slots, by_id, projections, games, scoring_config),
        "matchup": await _matchup_projection(team, league, week, year, games, db),
        "roster": [_serialize_roster_player(p, p.id in starter_ids, scoring_config, games, week, year, projections)
                   for p in roster],
    }


async def team_week_projection(team: Team, league: League, week: int, year: int,
                               games: WeekGames, db: AsyncSession) -> float | None:
    """Projected points for the lineup this team would score right now."""
    roster = await _resolve_roster(team, db)
    projections = await week_projections(roster, year, week, db)
    if projections is None:
        return None
    current = await _current_lineup(team, league, roster, week, year, db)
    return projected_total(current.slots, {p.id: p for p in roster}, projections, games, league.scoring_config or {})


async def _matchup_projection(team: Team, league: League, week: int, year: int,
                              games: WeekGames, db: AsyncSession) -> dict | None:
    """This week's opponent and both projected totals, or None on a bye week."""
    teams = (await db.execute(select(Team).where(Team.league_id == league.id))).scalars().all()
    opponent_id = next((b if a == team.id else a for a, b in _effective_matchups(league, teams, week)
                        if team.id in (a, b)), None)
    opponent = next((t for t in teams if t.id == opponent_id), None)
    if opponent is None:
        return None
    return {
        "opponent_team_id": opponent.id,
        "opponent_name": opponent.name,
        "projected": await team_week_projection(team, league, week, year, games, db),
        "opponent_projected": await team_week_projection(opponent, league, week, year, games, db),
    }


class SlotIn(BaseModel):
    slot: str
    player_id: str | None = None


class SetLineupRequest(BaseModel):
    """Either slots (preferred) or the older flat starters list, which the
    server places into slots itself."""
    starters: list[str] | None = None
    slots: list[SlotIn] | None = None


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
    """Save a lineup. Every starter must be rostered and fit the slot he's
    in (FLEX takes RB/WR/TE, SUPERFLEX adds QB, IDP_FLEX takes DL/LB/DB).
    A player whose game has kicked off can't be moved in or out of the
    starters (409). Starting someone ruled out or on bye is allowed but
    comes back in warnings and issues."""
    team, league = await _get_team_league_or_404(team_id, db)
    require_team_or_league_access(team, league, current_user)
    if get_best_ball_settings(league)["enabled"]:
        raise HTTPException(
            status_code=400,
            detail="This league uses Best-Ball auto-lineups -- starters are selected automatically each week.",
        )
    if data.slots is None and data.starters is None:
        raise HTTPException(status_code=422, detail="Send slots or starters.")

    roster_slots = _league_slot_settings(league)
    roster = await _resolve_roster(team, db)
    positions = {p.id: p.position for p in roster}
    names = {p.id: f"{p.first_name} {p.last_name}" for p in roster}
    roster_set = set(team.roster or [])

    if data.slots is not None:
        submitted = [s.model_dump() for s in data.slots]
        invalid = [s["player_id"] for s in submitted if s["player_id"] and s["player_id"] not in roster_set]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Not on this team's roster: {invalid}")
        try:
            slots = validate_slots(submitted, positions, names, roster_slots)
        except LineupError as e:
            raise HTTPException(status_code=422, detail=str(e))
    else:
        starters = list(dict.fromkeys(data.starters or []))
        invalid = [pid for pid in starters if pid not in roster_set]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Not on this team's roster: {invalid}")
        total_slots = len(expand_slots(roster_slots))
        if len(starters) > total_slots:
            raise HTTPException(
                status_code=422,
                detail=f"Too many starters: {len(starters)} submitted, this league only has {total_slots} starting slots",
            )
        slots, left = place_starters(starters, positions, roster_slots)
        if left:
            who = ", ".join(f"{names.get(pid, pid)} ({positions.get(pid)})" for pid in left)
            raise HTTPException(status_code=422, detail=f"No open starting slot for {who}.")

    games = await load_week_games(year, week, db)
    current = await _current_lineup(team, league, roster, week, year, db)
    before, after = set(current.starters), set(starters_of(slots))
    moved_locked = [p for p in roster if games.locked(p.team) and ((p.id in before) != (p.id in after))]
    if moved_locked:
        who = ", ".join(names[p.id] for p in moved_locked)
        raise HTTPException(status_code=409, detail=f"Locked at kickoff, can't be moved: {who}.")

    saved = await _save(team_id, week, year, slots, db)
    issues = lineup_issues(slots, _player_states(roster, games))
    return {
        "status": "ok",
        "starters": saved,
        "slots": slots,
        "warnings": [i["message"] for i in issues if i["kind"] in ("out", "bye")],
        "issues": issues,
    }


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
    ranked by this week's league-scored projection when the week has any,
    else effective_season_stats (this season's production once it has
    any, else last season's total). Never starts a player who's ruled out
    or on bye. Players whose game has kicked off stay where they are.
    Saves the result, same as a manual set."""
    team, league = await _get_team_league_or_404(team_id, db)
    require_team_or_league_access(team, league, current_user)
    if get_best_ball_settings(league)["enabled"]:
        raise HTTPException(
            status_code=400,
            detail="This league uses Best-Ball auto-lineups -- starters are selected automatically each week.",
        )

    roster_slots = _league_slot_settings(league)
    scoring_config = league.scoring_config or {}
    roster = await _resolve_roster(team, db)
    games = await load_week_games(year, week, db)
    current = await _current_lineup(team, league, roster, week, year, db)

    locked = {p.id for p in roster if games.locked(p.team)}
    kept = [e for e in current.slots if e["player_id"] in locked]
    counts = dict(roster_slots)
    for e in kept:
        counts[e["slot"]] -= 1

    skipped_inactive = [f"{p.first_name} {p.last_name}" for p in roster if p.id not in locked and _is_inactive(p)]
    # Rank by this week's projection when the week has any. A player
    # Sleeper doesn't project ranks last, not on last season's total.
    projections = await week_projections(roster, year, week, db)
    pool = {}
    for p in roster:
        if p.id in locked or _is_inactive(p) or games.on_bye(p.team):
            continue
        if projections is not None:
            stats = projections.get(p.id) or {}
        else:
            stats, _ = effective_season_stats(p)
        pool[p.id] = {"stats": stats, "position": p.position, "name": f"{p.first_name} {p.last_name}"}

    result = _run_optimizer(pool, scoring_config, counts)
    picked = [{"slot": a["slot"], "player_id": a["player_id"]} for a in result["lineup"]]
    positions = {p.id: p.position for p in roster}
    slots = validate_slots(kept + picked, positions, {}, roster_slots)
    starters = await _save(team_id, week, year, slots, db)
    return {"status": "ok", "starters": starters, "slots": slots, "optimal_score": result["optimal_score"],
            "skipped_inactive": skipped_inactive,
            "ranked_by": "projection" if projections is not None else "season",
            "kept_locked": [f"{p.first_name} {p.last_name}" for p in roster if p.id in {e["player_id"] for e in kept}]}
