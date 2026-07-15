"""
Standings Service

Handles weekly scoring calculation, standings computation,
and head-to-head matchup pairing for fantasy football leagues.
"""
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func

from app.models.team import Team
from app.models.league import League
from app.models.player import Player
from app.models.weekly_score import WeeklyScore
from app.models.coach import Coach
from app.services.scoring_engine import calculate_player_score
from app.services.sleeper_sync import fetch_weekly_stats


async def _flat_weekly_coach_bonus(team_id: str, db: AsyncSession) -> float:
    """
    Sum flat per-week bonuses from a team's active coaching staff.

    Only bonus_type == "flat_weekly" is applied here — other bonus_type values
    (e.g. "points_per_win") depend on a week's win/loss outcome, which isn't
    known until get_standings() compares matchups, so they're stored but not
    yet scored.
    """
    result = await db.execute(
        select(Coach).where(
            Coach.team_id == team_id,
            Coach.is_active == True,  # noqa: E712
            Coach.bonus_type == "flat_weekly",
        )
    )
    coaches = result.scalars().all()
    return sum(c.bonus_value or 0.0 for c in coaches)


def _build_round_robin_schedule(team_ids: List[str], week: int) -> List[Tuple[str, str]]:
    """
    Build a round-robin schedule for a list of team IDs.

    Uses the classic circle method: fix the first team and rotate the rest.
    The week number determines the rotation offset.

    Returns a list of (team_a, team_b) tuples representing matchups.
    """
    n = len(team_ids)
    if n < 2:
        return []

    # Create a circular list; team at index 0 is fixed
    teams = list(team_ids)
    if n % 2 != 0:
        teams.append(None)  # bye week placeholder

    num_rounds = len(teams) - 1
    offset = (week - 1) % num_rounds if num_rounds > 0 else 0

    # Rotate all teams except the first
    fixed = teams[0]
    rotating = list(teams[1:])
    for _ in range(offset):
        rotating = [rotating[-1]] + rotating[:-1]
    teams_rotated = [fixed] + rotating

    # Pair front-to-back
    matchups = []
    half = len(teams_rotated) // 2
    for i in range(half):
        a = teams_rotated[i]
        b = teams_rotated[-(i + 1)]
        if a is not None and b is not None:
            matchups.append((a, b))

    return matchups


async def calculate_week(
    league_id: str,
    week: int,
    year: int,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Calculate scores for all teams in a league for a given week.

    For each team:
    1. Reads the roster (list of player IDs) from the Team model
    2. Looks up player positions from the Player model
    3. Gets weekly stats (Sleeper API or Player.week_stats)
    4. Uses scoring_engine.calculate_player_score() for each player
    5. Stores a WeeklyScore record

    Args:
        league_id: League identifier
        week: Week number (1-18)
        year: Season year
        db: AsyncSession

    Returns:
        Dict with results summary
    """
    # Get league for scoring config
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()
    if not league:
        raise ValueError(f"League {league_id} not found")
    scoring_config = league.scoring_config or {}

    # Get all teams in the league
    teams_result = await db.execute(
        select(Team).where(Team.league_id == league_id)
    )
    teams = teams_result.scalars().all()

    if not teams:
        return {"league_id": league_id, "week": week, "year": year, "teams_scored": 0, "scores": []}

    # Collect all player IDs across all rosters to batch-lookup
    all_player_ids = set()
    for team in teams:
        if team.roster:
            all_player_ids.update(team.roster)

    # Batch load player data (sleeper_id -> position mapping)
    player_positions: Dict[str, str] = {}
    if all_player_ids:
        players_result = await db.execute(
            select(Player).where(Player.id.in_(list(all_player_ids)))
        )
        players = players_result.scalars().all()
        for p in players:
            player_positions[p.id] = p.position

    # Try to fetch stats from Sleeper API; fall back to Player.week_stats
    try:
        sleeper_stats = await fetch_weekly_stats(year, week)
        use_sleeper = True
    except Exception:
        use_sleeper = False
        sleeper_stats = {}

    results = []

    for team in teams:
        roster_ids = team.roster or []

        if not roster_ids:
            # Empty roster — score is 0
            total_score = 0.0
            lineup_data = {"total": 0.0, "breakdown": {}}
        else:
            # Build per-player stats dict
            week_stats: Dict[str, Dict[str, Any]] = {}
            player_id_to_sleeper: Dict[str, str] = {}
            sleeper_to_player_id: Dict[str, str] = {}

            # Map player internal IDs to Sleeper IDs
            if all_player_ids:
                sleeper_result = await db.execute(
                    select(Player).where(Player.id.in_(roster_ids))
                )
                sleeper_players = sleeper_result.scalars().all()
                for sp in sleeper_players:
                    player_id_to_sleeper[sp.id] = sp.sleeper_id
                    sleeper_to_player_id[sp.sleeper_id] = sp.id

            for pid in roster_ids:
                if use_sleeper and pid in player_id_to_sleeper:
                    sleeper_id = player_id_to_sleeper[pid]
                    stats = sleeper_stats.get(sleeper_id, {})
                else:
                    # Fallback: load player from DB for week_stats
                    p_result = await db.execute(select(Player).where(Player.id == pid))
                    player = p_result.scalar_one_or_none()
                    stats = (player.week_stats or {}).get(str(week), {}) if player else {}
                week_stats[pid] = stats

            # Calculate score per player
            breakdown = {}
            total_score = 0.0
            for pid in roster_ids:
                stats = week_stats.get(pid, {})
                position = player_positions.get(pid, "UNKNOWN")
                player_score = calculate_player_score(stats, scoring_config, position)
                breakdown[pid] = {
                    "score": player_score,
                    "stats": stats,
                    "position": position,
                }
                total_score += player_score

            total_score = round(total_score, 2)
            lineup_data = {"total": total_score, "breakdown": breakdown}

        coach_bonus = await _flat_weekly_coach_bonus(team.id, db)
        if coach_bonus:
            total_score = round(total_score + coach_bonus, 2)
            lineup_data["total"] = total_score
            lineup_data["coach_bonus"] = coach_bonus

        # Upsert WeeklyScore record
        existing_result = await db.execute(
            select(WeeklyScore).where(
                WeeklyScore.league_id == league_id,
                WeeklyScore.team_id == team.id,
                WeeklyScore.week == week,
                WeeklyScore.year == year,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.total_score = total_score
            existing.lineup_data = lineup_data
        else:
            score_record = WeeklyScore(
                league_id=league_id,
                team_id=team.id,
                week=week,
                year=year,
                total_score=total_score,
                lineup_data=lineup_data,
            )
            db.add(score_record)

        results.append({
            "team_id": team.id,
            "team_name": team.name,
            "total_score": total_score,
        })

    await db.commit()

    return {
        "league_id": league_id,
        "week": week,
        "year": year,
        "teams_scored": len(results),
        "scores": results,
    }


async def get_standings(league_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Get current standings for a league by analyzing weekly scores
    and head-to-head matchups.

    Queries all WeeklyScores for the league, groups by team,
    computes wins/losses/ties from head-to-head comparisons,
    and returns ordered standings.

    Returns:
        List of dicts with: team_id, team_name, wins, losses, ties,
        points_for, points_against
    """
    # Get all teams for name lookup
    teams_result = await db.execute(
        select(Team).where(Team.league_id == league_id)
    )
    teams = teams_result.scalars().all()
    team_map = {t.id: t.name for t in teams}

    if not teams:
        return []

    # Get all weekly scores for this league
    scores_result = await db.execute(
        select(WeeklyScore).where(WeeklyScore.league_id == league_id)
    )
    all_scores = scores_result.scalars().all()

    if not all_scores:
        # Return teams with zero stats
        return [
            {
                "team_id": t.id,
                "team_name": t.name,
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "points_for": 0.0,
                "points_against": 0.0,
            }
            for t in teams
        ]

    # Group scores by week
    weekly_scores: Dict[Tuple[int, int], Dict[str, float]] = {}  # (year, week) -> {team_id: score}
    for ws in all_scores:
        key = (ws.year, ws.week)
        if key not in weekly_scores:
            weekly_scores[key] = {}
        weekly_scores[key][ws.team_id] = ws.total_score

    # Initialize standings
    standings: Dict[str, Dict[str, Any]] = {}
    for t in teams:
        standings[t.id] = {
            "team_id": t.id,
            "team_name": t.name,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "points_for": 0.0,
            "points_against": 0.0,
        }

    # Aggregate points
    for ws in all_scores:
        standings[ws.team_id]["points_for"] += ws.total_score

    # Compute wins/losses/ties from head-to-head matchups each week
    team_ids = [t.id for t in teams]

    for (year, week), week_scores in weekly_scores.items():
        matchups = _build_round_robin_schedule(team_ids, week)
        for team_a, team_b in matchups:
            score_a = week_scores.get(team_a, 0.0)
            score_b = week_scores.get(team_b, 0.0)

            # Points against
            standings[team_a]["points_against"] += score_b
            standings[team_b]["points_against"] += score_a

            if score_a > score_b:
                standings[team_a]["wins"] += 1
                standings[team_b]["losses"] += 1
            elif score_b > score_a:
                standings[team_b]["wins"] += 1
                standings[team_a]["losses"] += 1
            else:
                standings[team_a]["ties"] += 1
                standings[team_b]["ties"] += 1

    # Round floats
    for entry in standings.values():
        entry["points_for"] = round(entry["points_for"], 2)
        entry["points_against"] = round(entry["points_against"], 2)

    # Sort: wins desc, then points_for desc
    sorted_standings = sorted(
        standings.values(),
        key=lambda x: (x["wins"], x["points_for"]),
        reverse=True,
    )

    return sorted_standings


async def get_weekly_matchups(
    league_id: str,
    week: int,
    year: int,
    db: AsyncSession,
) -> List[Dict[str, Any]]:
    """
    Get head-to-head matchups for a specific week.

    Pairs teams based on round-robin schedule and returns
    each matchup with team names and scores.

    Returns:
        List of matchups: {team_a: {id, name, score}, team_b: {id, name, score}}
    """
    # Get all teams in the league
    teams_result = await db.execute(
        select(Team).where(Team.league_id == league_id)
    )
    teams = teams_result.scalars().all()
    team_map = {t.id: t.name for t in teams}

    team_ids = [t.id for t in teams]
    matchups = _build_round_robin_schedule(team_ids, week)

    # Fetch scores for this week
    scores_result = await db.execute(
        select(WeeklyScore).where(
            WeeklyScore.league_id == league_id,
            WeeklyScore.week == week,
            WeeklyScore.year == year,
        )
    )
    week_scores = scores_result.scalars().all()
    score_map: Dict[str, float] = {ws.team_id: ws.total_score for ws in week_scores}

    result = []
    for team_a, team_b in matchups:
        # Alternate home/away by matchup index for variety
        is_home = len(result) % 2 == 0
        if is_home:
            matchup = {
                "home_team": team_map.get(team_a, "Unknown"),
                "home_team_id": team_a,
                "home_score": score_map.get(team_a, 0.0),
                "away_team": team_map.get(team_b, "Unknown"),
                "away_team_id": team_b,
                "away_score": score_map.get(team_b, 0.0),
            }
        else:
            matchup = {
                "home_team": team_map.get(team_b, "Unknown"),
                "home_team_id": team_b,
                "home_score": score_map.get(team_b, 0.0),
                "away_team": team_map.get(team_a, "Unknown"),
                "away_team_id": team_a,
                "away_score": score_map.get(team_a, 0.0),
            }
        result.append(matchup)

    return result
