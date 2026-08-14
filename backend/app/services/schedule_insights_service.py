"""
Schedule & Strength-of-Schedule Tools (AI Co-Commissioner v1, Phase 2).

Zero-LLM, computed-data pattern -- same rationale as
league_health_service.py/insights_service.py: real arithmetic over
existing rows, plain-English explanation strings generated in Python,
no persistence, no rate limit. Flags which teams have a notably
harder- or easier-than-usual run of remaining opponents.

Deliberately does NOT suggest schedule adjustments -- no mid-season
schedule-edit mechanism exists anywhere in this app (confirmed while
planning this feature), so advisory text pointing at a capability the
app can't actually act on would be misleading. This stays pure
analysis/flagging, same "don't imply precision you don't have"
principle league_health_service's co-owned-team note already
established.

No schedule is ever persisted (League has no schedule field) -- a
week counts as "played" once it has WeeklyScore rows, same convention
standings_service.get_season_schedule already uses, rather than
depending on the scheduler's live-week global (which resets on every
redeploy -- not safe for a correctness-bearing "what's remaining"
calculation).
"""
from __future__ import annotations

import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.services.standings_service import (
    get_standings,
    _effective_matchups,
    DEFAULT_SEASON_WEEKS,
)
from app.services.playoff_service import get_playoff_settings

# A team's average remaining-opponent strength over just its next
# NEXT_STRETCH_WEEKS, expressed as a ratio against its own
# full-remaining-season opponent average, above/below which that
# upcoming stretch is flagged as notably hard/easy. Starting point,
# tunable after seeing real data.
HARD_STRETCH_RATIO = 1.15
EASY_STRETCH_RATIO = 0.85
NEXT_STRETCH_WEEKS = 3


async def compute_strength_of_schedule(league: League, db: AsyncSession) -> dict[str, Any]:
    playoff_settings = get_playoff_settings(league)
    season_weeks = playoff_settings["regular_season_weeks"] if playoff_settings["enabled"] else DEFAULT_SEASON_WEEKS

    weeks_result = await db.execute(
        select(WeeklyScore.week).where(WeeklyScore.league_id == league.id).distinct()
    )
    played_weeks = {row[0] for row in weeks_result.all()}
    next_week = (max(played_weeks) + 1) if played_weeks else 1
    remaining_weeks = list(range(next_week, season_weeks + 1))

    if not remaining_weeks:
        return {"available": False, "reason": "No remaining regular-season weeks."}

    teams_result = await db.execute(select(Team).where(Team.league_id == league.id))
    teams = teams_result.scalars().all()
    if not teams:
        return {"available": False, "reason": "No teams yet."}

    # Alive-only -- an eliminated Guillotine team has no remaining
    # schedule at all (always True for every non-Guillotine team,
    # since eliminated_week is never set there).
    alive_teams = [t for t in teams if t.eliminated_week is None]

    is_guillotine = league.league_type == LeagueType.GUILLOTINE
    if is_guillotine and len(alive_teams) == 2:
        # _effective_matchups force-pairs the last two survivors every
        # remaining week -- SOS collapses to a degenerate 1-opponent
        # case, worth reporting explicitly rather than run through the
        # normal flagging logic below, which would be meaningless here.
        names = sorted(t.name for t in alive_teams)
        return {
            "available": True,
            "finale": True,
            "summary": f"Down to the final two -- {names[0]} and {names[1]} play each other every remaining week.",
            "teams": [],
        }

    strength_by_team = await _opponent_strength_by_team(league, db)
    league_avg_strength = statistics.mean(strength_by_team.values()) if strength_by_team else 0.0

    opponents_by_team: dict[str, list[str | None]] = {t.id: [] for t in alive_teams}
    for week in remaining_weeks:
        matchups = _effective_matchups(league, teams, week)
        opponent_of: dict[str, str] = {}
        for a, b in matchups:
            opponent_of[a] = b
            opponent_of[b] = a
        for t in alive_teams:
            opponents_by_team[t.id].append(opponent_of.get(t.id))

    team_results = [
        _team_sos_result(t, opponents_by_team[t.id], strength_by_team, league_avg_strength)
        for t in alive_teams
    ]
    team_results.sort(key=lambda r: r["sos_score"] or 0, reverse=True)

    return {
        "available": True,
        "finale": False,
        "remaining_weeks": remaining_weeks,
        "teams": team_results,
    }


async def _opponent_strength_by_team(league: League, db: AsyncSession) -> dict[str, float]:
    """Points-for-per-game as the team-strength proxy (no power ranking
    or projection model exists anywhere in this app to reuse instead).
    Dual-Squad leagues use each team's PARTNER-PAIR combined points
    per game (both partners' points_for summed, divided by one
    partner's own games-played -- partners always play the same weeks,
    so this is the pair's real per-week output, not diluted by naively
    summing both partners' games too), not its own individual points,
    as the opponent-strength value -- matching how that league type is
    already presented everywhere else (standings page's "Combined
    Pairs" table, AI prompt partner_context) -- even though matchups
    themselves still happen at the individual-team level (partners
    never play each other; _effective_matchups cross-wires around
    that)."""
    strength: dict[str, float] = {}
    if league.league_type == LeagueType.DUAL_SQUAD:
        # get_combined_standings sums BOTH partners' games played, not
        # just one -- dividing combined points_for by that double-counts
        # games (a pair's two individual teams always play the same
        # weeks, so either partner's own game count is the pair's real
        # "games played as a unit"). Using individual get_standings
        # rows directly, summed per pair, avoids that trap.
        individual = await get_standings(league.id, db)
        by_team_id = {row["team_id"]: row for row in individual}
        partner_of = {tid: pid for tid, pid in (await db.execute(
            select(Team.id, Team.partner_team_id).where(Team.league_id == league.id)
        )).all()}
        for team_id, row in by_team_id.items():
            partner_id = partner_of.get(team_id)
            partner_row = by_team_id.get(partner_id) if partner_id else None
            games = row["wins"] + row["losses"] + row["ties"]
            combined_points = row["points_for"] + (partner_row["points_for"] if partner_row else 0.0)
            strength[team_id] = round(combined_points / games, 2) if games else 0.0
    else:
        for row in await get_standings(league.id, db):
            games = row["wins"] + row["losses"] + row["ties"]
            strength[row["team_id"]] = round(row["points_for"] / games, 2) if games else 0.0
    return strength


def _team_sos_result(
    team: Team,
    opponent_ids: list[str | None],
    strength_by_team: dict[str, float],
    league_avg_strength: float,
) -> dict[str, Any]:
    opponents = [o for o in opponent_ids if o is not None]
    if not opponents:
        return {
            "team_id": team.id,
            "team_name": team.name,
            "sos_score": None,
            "flag": None,
            "summary": "No remaining opponents found on the schedule.",
        }

    opponent_strengths = [strength_by_team.get(o, league_avg_strength) for o in opponents]
    sos_score = round(statistics.mean(opponent_strengths), 2)

    next_stretch = opponent_strengths[:NEXT_STRETCH_WEEKS]
    next_stretch_avg = round(statistics.mean(next_stretch), 2) if next_stretch else sos_score

    flag = None
    if sos_score > 0 and next_stretch_avg / sos_score >= HARD_STRETCH_RATIO:
        flag = "hard_stretch"
        summary = (
            f"Next {len(next_stretch)} weeks are tougher than usual -- opponents averaging "
            f"{next_stretch_avg} pts/game vs. this team's full-remaining-season opponent average of {sos_score}."
        )
    elif sos_score > 0 and next_stretch_avg / sos_score <= EASY_STRETCH_RATIO:
        flag = "easy_stretch"
        summary = (
            f"Next {len(next_stretch)} weeks look easier than usual -- opponents averaging "
            f"{next_stretch_avg} pts/game vs. this team's full-remaining-season opponent average of {sos_score}."
        )
    else:
        summary = f"Remaining opponents average {sos_score} pts/game -- no unusually easy or hard stretch ahead."

    return {
        "team_id": team.id,
        "team_name": team.name,
        "sos_score": sos_score,
        "next_stretch_average": next_stretch_avg,
        "flag": flag,
        "summary": summary,
    }
