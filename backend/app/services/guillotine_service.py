"""
Guillotine elimination (Phase 4, "Guillotine + Custom Twist").

One league's worth of "who's out this week" processing -- mirrors
playoff_service's shape (a single per-league entry point the scheduler
calls once a week is truly final), kept as its own module/call so an
elimination bug can't affect regular scoring, and vice versa, the same
separation-of-concerns reasoning process_league_playoffs already
established.

Elimination cadence (binding decision, resolved via AskUserQuestion, not
configurable): week 1 start, no grace period, stops once exactly 2 teams
remain alive -- those two just play out the rest of the season
head-to-head (see standings_service._effective_matchups' finale-pairing
fix-up). Tiebreak for the week's lowest score: raw WeeklyScore.total_score
first, then fewest cumulative points_for through that week, then
earliest Team.created_at -- deterministic, not user-configurable.
"""
from typing import Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.models.contract import Contract
from app.services.standings_service import get_standings
from app.services.salary_cap_service import get_salary_cap_settings
from app.services.notification_service import notify_team_owners
from app.models.notification import NotificationType


async def _deactivate_contracts(team: Team, league: League, db: AsyncSession) -> None:
    """Salary-Cap interaction (Phase 5): Guillotine and salary cap are
    two independent bolt-ons that can coexist on one league. When an
    eliminated team's roster is wiped, its active Contract rows are
    marked is_active=False too -- no dead money, since dead money
    constrains a team's FUTURE spending, and an eliminated team already
    has zero future spending capacity (the existing process_waivers/
    claim_co_owner gates already block it from acting at all). Leaving
    those rows is_active=True forever would just be a driftable no-op
    that could wrongly inflate a future query if this invariant is ever
    assumed elsewhere. A strict no-op for a non-cap league (nothing to
    deactivate)."""
    if not get_salary_cap_settings(league)["enabled"]:
        return
    await db.execute(
        update(Contract)
        .where(Contract.league_id == league.id, Contract.team_id == team.id, Contract.is_active == True)  # noqa: E712
        .values(is_active=False)
    )


async def _self_heal_ghost_rosters(all_teams: list[Team], league: League, db: AsyncSession) -> bool:
    """Any already-eliminated team should have an empty roster (see the
    CAS dump in process_league_guillotine below). Re-checked on every
    call, not just at the moment of elimination, so a lost CAS race (or
    any other reason the dump didn't land) self-heals on the very next
    scheduler tick or manual trigger instead of staying broken forever.
    Returns True if anything was changed (caller commits)."""
    changed = False
    for team in all_teams:
        if team.eliminated_week is not None and team.roster:
            await db.execute(
                update(Team)
                .where(Team.id == team.id, Team.roster_version == team.roster_version)
                .values(roster=[], roster_version=Team.roster_version + 1)
            )
            await _deactivate_contracts(team, league, db)
            changed = True
    return changed


async def process_league_guillotine(league: League, year: int, week: int, db: AsyncSession) -> Optional[dict[str, Any]]:
    """Determines and records this week's elimination for a GUILLOTINE
    league, if one hasn't already been recorded for this exact week.

    Returns a dict describing the elimination, or None if nothing
    happened this call (wrong league type, finale already reached,
    already processed this week, or not every alive team has a
    WeeklyScore yet). Safe to call more than once for the same week --
    idempotent by construction (see the `already` check).

    Known, deliberately-accepted limitation: this assumes weeks are
    always processed in chronological order (true for both real entry
    points -- the scheduler's once-per-transition hook and the
    commissioner's manual endpoint, both of which only ever advance
    forward). calculate_week itself has an identical no-protection-
    against-out-of-order-calls property already.
    """
    if league.league_type != LeagueType.GUILLOTINE:
        return None

    teams_result = await db.execute(select(Team).where(Team.league_id == league.id))
    all_teams = list(teams_result.scalars().all())

    if await _self_heal_ghost_rosters(all_teams, league, db):
        await db.commit()

    if any(t.eliminated_week == week for t in all_teams):
        return None  # already processed this exact week

    alive = [t for t in all_teams if t.eliminated_week is None]
    if len(alive) <= 2:
        return None  # finale reached (or a tiny league) -- no more eliminations, ever

    scores_result = await db.execute(
        select(WeeklyScore).where(
            WeeklyScore.league_id == league.id,
            WeeklyScore.week == week,
            WeeklyScore.year == year,
            WeeklyScore.team_id.in_([t.id for t in alive]),
        )
    )
    scores_by_team = {ws.team_id: ws for ws in scores_result.scalars().all()}
    if any(t.id not in scores_by_team for t in alive):
        # calculate_week hasn't scored every alive team yet this week --
        # don't guess. Mirrors notify_matchup_results' own "only trust an
        # actually-scored row" caution.
        return None

    standings = await get_standings(league.id, db, through_week=week)
    points_for_map = {s["team_id"]: s["points_for"] for s in standings}

    def _tiebreak_key(t: Team):
        return (scores_by_team[t.id].total_score, points_for_map.get(t.id, 0.0), t.created_at)

    eliminated_team = min(alive, key=_tiebreak_key)
    eliminated_score = scores_by_team[eliminated_team.id].total_score

    await db.execute(
        update(Team)
        .where(Team.id == eliminated_team.id, Team.roster_version == eliminated_team.roster_version)
        .values(roster=[], roster_version=Team.roster_version + 1)
    )
    eliminated_team.eliminated_week = week
    await _deactivate_contracts(eliminated_team, league, db)

    link = f"/leagues/{league.id}/standings"
    await notify_team_owners(
        db, eliminated_team, NotificationType.TEAM_ELIMINATED,
        f"{eliminated_team.name} was eliminated in week {week} with the lowest score ({eliminated_score:g}).",
        league.id, link,
    )
    await db.commit()

    return {
        "eliminated_team_id": eliminated_team.id,
        "eliminated_team_name": eliminated_team.name,
        "week": week,
        "score": eliminated_score,
    }
