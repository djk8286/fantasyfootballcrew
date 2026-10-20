"""Everything the league home page leads with, in one payload: the
viewer's matchup (live or projected), what's wrong with their lineup,
last week's recap, the week's scoreboard, standings and recent activity."""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.lineups import (
    _current_lineup,
    _league_slot_settings,
    _player_states,
    _resolve_roster,
    _run_optimizer,
    load_week_games,
    projected_total,
    week_projections,
)
from app.models.league import League
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.services.best_ball_service import get_best_ball_settings
from app.services.lineup_slots import lineup_issues
from app.services.season_weeks import WeekState, league_start_week, season_week_states
from app.services.standings_service import _effective_matchups, get_standings
from app.services.team_activity_service import league_activity, streak, weekly_results

ISSUE_ORDER = {"empty": 0, "out": 1, "bye": 2, "illegal": 3}


def scoring_label(scoring_config: dict | None) -> str:
    """PPR, Half PPR or Standard, from the points per reception."""
    rec = 0.0
    for rules in (scoring_config or {}).values():
        if isinstance(rules, dict) and "rec" in rules:
            rec = float(rules["rec"] or 0)
            break
    return "PPR" if rec >= 1 else "Half PPR" if rec > 0 else "Standard"


async def _team_week(team: Team, league: League, week: int, year: int, games, db: AsyncSession) -> dict:
    """Projected total for the lineup that scores now, plus its issues."""
    roster = await _resolve_roster(team, db)
    current = await _current_lineup(team, league, roster, week, year, db)
    projections = await week_projections(roster, year, week, db)
    issues = lineup_issues(current.slots, _player_states(roster, games), current.unplaced)
    issues.sort(key=lambda i: ISSUE_ORDER.get(i["kind"], 9))
    return {
        "projected": projected_total(current.slots, {p.id: p for p in roster}, projections, games, league.scoring_config or {}),
        "issues": issues,
        "has_lineup_set": current.has_lineup_set,
    }


async def _recap(league: League, team: Team, opp_name: dict, results: list[dict], week: int, db: AsyncSession) -> dict | None:
    """Last finished game for this team, with how many points sat on the
    bench compared with the best legal lineup from the same roster."""
    mine = [r for r in results if team.id in (r["team_a"], r["team_b"]) and r["week"] < week]
    if not mine:
        return None
    r = mine[-1]
    me, them = (r["score_a"], r["score_b"]) if r["team_a"] == team.id else (r["score_b"], r["score_a"])
    opponent = r["team_b"] if r["team_a"] == team.id else r["team_a"]
    ws = (await db.execute(select(WeeklyScore).where(
        WeeklyScore.team_id == team.id, WeeklyScore.week == r["week"], WeeklyScore.year == r["year"],
    ))).scalar_one_or_none()
    breakdown = ((ws.lineup_data or {}).get("breakdown") or {}) if ws else {}
    optimal = None
    if breakdown:
        pool = {pid: {"stats": e.get("stats") or {}, "position": e.get("position"), "name": pid} for pid, e in breakdown.items()}
        optimal = round(_run_optimizer(pool, league.scoring_config or {}, _league_slot_settings(league))["optimal_score"], 2)
    return {
        "week": r["week"],
        "result": "W" if me > them else "L" if me < them else "T",
        "score": me,
        "opponent_score": them,
        "opponent_team_id": opponent,
        "opponent_name": opp_name.get(opponent, "Unknown"),
        "optimal_score": optimal,
        "bench_points": round(max(0.0, optimal - me), 2) if optimal is not None else None,
    }


async def league_home(league: League, week: int, year: int, db: AsyncSession, viewer_id: str | None,
                      show_projections: bool = True) -> dict[str, Any]:
    """show_projections False (guests): per-team projected totals, which are
    built from each team's current lineup, come back null."""
    teams = list((await db.execute(select(Team).where(Team.league_id == league.id))).scalars().all())
    names = {t.id: t.name for t in teams}
    mine = next((t for t in teams if viewer_id and viewer_id in (t.owner_id, t.co_owner_id)), None)
    games = await load_week_games(year, week, db)
    states = await season_week_states(year, db)
    status = states.get(week, WeekState.UNKNOWN)

    scores = {ws.team_id: ws.total_score for ws in (await db.execute(select(WeeklyScore).where(
        WeeklyScore.league_id == league.id, WeeklyScore.week == week, WeeklyScore.year == year,
    ))).scalars().all()}
    show_scores = status != WeekState.UPCOMING

    by_team: dict[str, dict] = {}
    for t in teams:
        by_team[t.id] = await _team_week(t, league, week, year, games, db) if status != WeekState.FINAL else \
            {"projected": None, "issues": [], "has_lineup_set": True}

    def side(tid: str) -> dict:
        return {"team_id": tid, "name": names.get(tid, "Unknown"),
                "score": scores.get(tid) if show_scores else None,
                "projected": by_team.get(tid, {}).get("projected") if show_projections else None}

    scoreboard = [{"team_a": side(a), "team_b": side(b), "mine": bool(mine) and mine.id in (a, b)}
                  for a, b in _effective_matchups(league, teams, week)]

    my_matchup = None
    if mine:
        m = next((x for x in scoreboard if x["mine"]), None)
        if m:
            me, opp = (m["team_a"], m["team_b"]) if m["team_a"]["team_id"] == mine.id else (m["team_b"], m["team_a"])
            my_matchup = {"me": me, "opponent": opp}

    results = await weekly_results(league, teams, db)
    standings = await get_standings(league.id, db)
    rows = [{
        "rank": i + 1, "team_id": r["team_id"], "name": r["team_name"],
        "wins": r["wins"], "losses": r["losses"], "ties": r["ties"],
        "points_for": r["points_for"], "streak": streak(results, r["team_id"]),
        "mine": bool(mine) and r["team_id"] == mine.id,
    } for i, r in enumerate(standings)]

    my_issues = by_team.get(mine.id, {}).get("issues", []) if mine else []
    owners = {t.owner_id for t in teams} | {t.co_owner_id for t in teams}
    return {
        "league": {
            "id": league.id,
            "name": league.name,
            "league_type": getattr(league.league_type, "value", league.league_type),
            "visibility": getattr(league.visibility, "value", league.visibility),
            "draft_status": getattr(league.draft_status, "value", league.draft_status),
            "team_count": len(teams),
            "max_teams": league.max_teams,
            "scoring": scoring_label(league.scoring_config),
            "best_ball": get_best_ball_settings(league)["enabled"],
            "is_commissioner": bool(viewer_id) and (viewer_id == league.commissioner_id or viewer_id in (league.co_commissioner_ids or [])),
            "is_member": bool(viewer_id) and viewer_id in owners,
        },
        "week": week,
        "year": year,
        "week_status": status,
        "league_start_week": await league_start_week(league.id, year, db),
        "my_team": {"id": mine.id, "name": mine.name, "has_lineup_set": by_team[mine.id]["has_lineup_set"]} if mine else None,
        "my_matchup": my_matchup,
        "top_issue": my_issues[0] if my_issues else None,
        "issue_count": len(my_issues),
        "last_week": await _recap(league, mine, names, results, week, db) if mine else None,
        "scoreboard": scoreboard,
        "standings": rows,
        "activity": await league_activity(league, teams, db, viewer_id=viewer_id, limit=8),
    }
