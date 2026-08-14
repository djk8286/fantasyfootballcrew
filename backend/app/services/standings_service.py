"""
Standings Service

Handles weekly scoring calculation, standings computation,
and head-to-head matchup pairing for fantasy football leagues.
"""
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func

from app.models.team import Team
from app.models.league import League, LeagueType
from app.models.player import Player
from app.models.weekly_score import WeeklyScore
from app.models.coach import Coach
from app.models.score_adjustment import ScoreAdjustment
from app.models.lineup import Lineup
from app.services.scoring_engine import calculate_player_score, calculate_optimal_lineup, DEFAULT_ROSTER_SLOTS
from app.services.sleeper_sync import fetch_weekly_stats
from app.services.notification_service import notify_team_owners
from app.models.notification import NotificationType
from app.services.best_ball_service import get_best_ball_settings


async def _weekly_adjustment_total(team_id: str, week: int, year: int, db: AsyncSession) -> float:
    """Sum of commissioner-added manual point adjustments for a team's
    week. Commissioner.create_adjustment stores these, but nothing was
    ever reading them back out -- they showed up in the commissioner
    panel's list but had zero effect on the team's actual score or the
    league standings."""
    result = await db.execute(
        select(ScoreAdjustment).where(
            ScoreAdjustment.team_id == team_id,
            ScoreAdjustment.week == week,
            ScoreAdjustment.year == year,
        )
    )
    return sum(a.amount for a in result.scalars().all())


async def _coach_bonus_sum(team_id: str, bonus_type: str, db: AsyncSession) -> float:
    """
    Sum bonus_value from a team's active coaching staff at a given
    bonus_type. Generalized from the original flat_weekly-only version
    (Phase 2 Step 2, "Front-Office finish-out") so "win_bonus" -- and any
    future bonus_type -- can share this same query instead of a
    copy-pasted near-duplicate.

    "flat_weekly" is unconditional (see calculate_week's first pass).
    "win_bonus" depends on a week's win/loss outcome, which calculate_week
    now determines itself via a second pass before this ever gets called
    for that bonus_type -- see calculate_week's docstring.
    """
    result = await db.execute(
        select(Coach).where(
            Coach.team_id == team_id,
            Coach.is_active == True,  # noqa: E712
            Coach.bonus_type == bonus_type,
        )
    )
    coaches = result.scalars().all()
    return sum(c.bonus_value or 0.0 for c in coaches)


# Rivalry Week (Phase 3, "Enhanced Conference/Rivalry") -- a commissioner-
# designated week where every team that wins its normal (same-conference)
# matchup that week gets a flat bonus, on top of any Coach win_bonus. Same
# JSON-blob-with-defaults pattern as DEFAULT_PLAYOFF_SETTINGS in
# playoff_service.py; lives here rather than a dedicated module since this
# is the module that actually consumes it (calculate_week, below).
# Entirely opt-in (enabled defaults False) and only meaningful for
# LeagueType.CONFERENCE -- see calculate_week's gate.
DEFAULT_RIVALRY_WEEK_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "week": None,
    "bonus_value": 0.0,
}


def get_rivalry_week_settings(league: League) -> Dict[str, Any]:
    merged = dict(DEFAULT_RIVALRY_WEEK_SETTINGS)
    merged.update(league.rivalry_week_settings or {})
    return merged


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


def _build_league_schedule(teams: List[Team], week: int) -> List[Tuple[str, str]]:
    """
    Round-robin matchups for a week, scoped to conference.

    Conference leagues ("6v6 conference battles... your squad vs. the
    rival conference") were only ever conference-restricted in the
    *standings display* -- the standings page groups by Team.conference,
    but the schedule/matchup generator below fed every team in the league
    into one flat round robin, so a team could just as easily be matched
    against the other conference as its own. This groups teams by
    conference first and runs an independent round robin per group, then
    merges the results -- each team now only ever plays within its own
    conference, all season.

    Standard/two-man leagues have conference == None for every team,
    which collapses to a single group (identical to a plain whole-league
    round robin -- this function is a strict superset of the old
    behavior, not a conference-only special case).
    """
    groups: Dict[Optional[str], List[str]] = {}
    for t in teams:
        groups.setdefault(t.conference, []).append(t.id)

    matchups: List[Tuple[str, str]] = []
    for group_team_ids in groups.values():
        matchups.extend(_build_round_robin_schedule(group_team_ids, week))
    return matchups


def _alive_at_week(team: Team, week: int) -> bool:
    """A team counts as alive for a given week if it's never been
    eliminated, or was eliminated exactly THIS week -- its own
    elimination is DETERMINED from this week's score (see
    guillotine_service.process_league_guillotine), so it must still
    appear as a real opponent for the week it goes out. Only weeks
    strictly AFTER its elimination week are skipped. Always True for
    every non-Guillotine team, since eliminated_week is never set there."""
    return team.eliminated_week is None or team.eliminated_week >= week


def _effective_matchups(league: Optional[League], teams: List[Team], week: int) -> List[Tuple[str, str]]:
    """_build_league_schedule's raw round-robin output, adjusted for
    Guillotine eliminations (Phase 4, "Guillotine + Custom Twist") --
    a strict no-op for every other league type, since Team.eliminated_week
    is always None there. _build_league_schedule itself is never
    regenerated/modified -- the fixed schedule stays exactly as
    generated at season start.

    1. Drop any pairing where either side was eliminated in a strictly
       earlier week -- that team's slot in the schedule just stops
       mattering ("stop-scoring slot", the resolved binding decision for
       this phase, as opposed to weekly schedule re-shrinking).
    2. Guillotine finale fix-up: a classic round-robin only pairs any
       two specific teams once per full cycle (num_rounds weeks), not
       every week -- so once elimination has whittled a league down to
       exactly two teams, most remaining weeks' raw schedule pairs each
       survivor against a now-eliminated team (dropped by step 1),
       producing no game that week. Once exactly two teams are alive in
       a GUILLOTINE league, force them onto a direct matchup every
       remaining week so the finale actually plays out head-to-head --
       the only special-casing this phase adds beyond the existing
       generator, and it only ever engages for the final two.
    """
    raw = _build_league_schedule(teams, week)
    alive_ids = {t.id for t in teams if _alive_at_week(t, week)}
    matchups = [(a, b) for (a, b) in raw if a in alive_ids and b in alive_ids]

    if league is not None and league.league_type == LeagueType.GUILLOTINE and len(alive_ids) == 2:
        pair = tuple(sorted(alive_ids))
        if pair not in matchups and (pair[1], pair[0]) not in matchups:
            matchups.append(pair)

    # 3. Dual-Squad/Mirror (Phase 7): drop any pairing where both teams
    #    are partners of each other (Team.partner_team_id) -- a
    #    manager's own two teams should never be scheduled against each
    #    other.
    #
    #    Verified by simulation (every week of a full round-robin
    #    cycle, n = 4/6/8/10/12 teams, adjacent-index partner pairing)
    #    that simply dropping these pairings is NOT safe alone: for
    #    n=4 (the minimum allowed size), the classic round-robin has
    #    exactly 3 rounds, which are exactly the 3 ways to split 4
    #    teams into 2 disjoint pairs -- so one full week, BOTH
    #    partner-pairs are scheduled against each other simultaneously,
    #    and dropping them both leaves that week with zero games at
    #    all. The same "more than one partner-pair drops in the same
    #    week" case recurs occasionally at larger n too (e.g. n=8 week
    #    7, n=12 week 11) -- it just never wipes the whole week once
    #    more games per round dilute it.
    #
    #    Fix: whenever 2+ partner-pairs drop in the same week,
    #    cross-wire them into new, guaranteed-non-partner matchups
    #    instead of leaving everyone on a bye -- pair dropped-pair[i]'s
    #    first team with dropped-pair[(i+1) mod n]'s second team, for
    #    every i. Since team X_i's only forbidden partner is Y_i (not
    #    any other pair's Y), and i+1 != i for n >= 2, this can never
    #    reconstruct an excluded pairing. A single partner-pair
    #    dropping alone (nothing to cross-wire against) still just
    #    produces an ordinary 2-team bye -- the same "byes are a
    #    normal seasonal occurrence" precedent this function's own
    #    odd-team-count handling already established.
    if league is not None and league.league_type == LeagueType.DUAL_SQUAD:
        partner_of = {t.id: t.partner_team_id for t in teams}
        dropped_pairs = [(a, b) for (a, b) in matchups if partner_of.get(a) == b]
        if dropped_pairs:
            matchups = [m for m in matchups if m not in dropped_pairs]
            n = len(dropped_pairs)
            if n >= 2:
                xs = [p[0] for p in dropped_pairs]
                ys = [p[1] for p in dropped_pairs]
                for i in range(n):
                    matchups.append(tuple(sorted((xs[i], ys[(i + 1) % n]))))
            # n == 1: no other dropped pair to cross-wire against --
            # both teams get a natural bye this week.

    return matchups


async def calculate_week(
    league_id: str,
    week: int,
    year: int,
    db: AsyncSession,
    sleeper_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Calculate scores for all teams in a league for a given week.

    sleeper_stats: pre-fetched fetch_weekly_stats(year, week) result, so a
    caller scoring many leagues for the same week (the scheduler's
    auto-calculate pass) can fetch it once instead of every league
    re-fetching the identical payload. None (the default, and what the
    commissioner-triggered manual endpoint still passes) means "fetch it
    yourself," preserving this function's original standalone behavior
    exactly.

    For each team:
    1. Reads its starters for this week (Lineup, if the team ever set one --
       otherwise its whole Team.roster, unchanged from before Lineup existed)
    2. Looks up player positions from the Player model
    3. Gets weekly stats (Sleeper API or Player.week_stats)
    4. Uses scoring_engine.calculate_player_score() for each player
    5. Applies flat_weekly coach bonuses and commissioner adjustments (this
       is "pass 1" -- see below) to get each team's BASE total
    6. Determines this week's matchup winners from those BASE totals (the
       same conference-aware round robin get_standings uses), then applies
       win_bonus coach bonuses only to the actual winners ("pass 2") --
       winner determination happens before any win_bonus is added, so a
       team's own win_bonus can never retroactively flip who won that same
       comparison. A team with no win_bonus coach, or with a bye week that
       round (odd team count), is completely unaffected -- byte-for-byte
       the same total it would have gotten before win_bonus existed.
    7. Stores a WeeklyScore record with the final total

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
    bb_settings = get_best_ball_settings(league)
    is_best_ball = bb_settings["enabled"]

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

    # A team with a saved Lineup for this exact (week, year) only scores
    # its chosen starters; a team that's never touched the lineup feature
    # scores its whole roster, same as before this existed -- see Lineup's
    # own docstring for why "no row" must mean "score everything", not
    # "score nothing". team.roster still filters which starters are even
    # valid (a stale Lineup naming a since-dropped player shouldn't score).
    team_ids = [t.id for t in teams]
    lineups_result = await db.execute(
        select(Lineup).where(Lineup.team_id.in_(team_ids), Lineup.week == week, Lineup.year == year)
    )
    starters_by_team: Dict[str, list] = {lu.team_id: (lu.starters or []) for lu in lineups_result.scalars().all()}

    # Batch load player data (sleeper_id -> position mapping)
    player_positions: Dict[str, str] = {}
    if all_player_ids:
        players_result = await db.execute(
            select(Player).where(Player.id.in_(list(all_player_ids)))
        )
        players = players_result.scalars().all()
        for p in players:
            player_positions[p.id] = p.position

    # Use the caller's pre-fetched stats if given; otherwise fetch our own
    # (falls back to Player.week_stats per-player below on failure either
    # way -- this only changes where the Sleeper call happens, not what
    # happens when there isn't one to use).
    if sleeper_stats is not None:
        use_sleeper = True
    else:
        try:
            sleeper_stats = await fetch_weekly_stats(year, week)
            use_sleeper = True
        except Exception:
            use_sleeper = False
            sleeper_stats = {}

    # PASS 1 -- base score for every team (roster + flat_weekly bonus +
    # commissioner adjustment), exactly as this function computed a team's
    # *entire* score before win_bonus existed. Deliberately NOT upserted
    # yet -- win/loss for the week isn't known until every team's base
    # total is in hand.
    base_totals: Dict[str, float] = {}
    lineup_data_by_team: Dict[str, Dict[str, Any]] = {}

    for team in teams:
        full_roster = set(team.roster or [])
        auto_starter_ids: Optional[list] = None
        if is_best_ball:
            # Best-Ball: start with the whole roster -- the optimizer
            # below picks the real starters once that week's actual
            # per-player stats are in hand. Any saved Lineup row is
            # ignored entirely for a best-ball league (there is no
            # manual starter selection in this mode).
            roster_ids = list(full_roster)
        elif team.id in starters_by_team:
            # Lineup exists -- only score starters, and only ones still
            # actually on the roster (protects against a stale Lineup
            # naming a player who's since been dropped/traded away).
            roster_ids = [pid for pid in starters_by_team[team.id] if pid in full_roster]
        else:
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

            if is_best_ball:
                # Pick the real per-week-optimal starters from the whole
                # roster, using the SAME week_stats already fetched above
                # (no second stats fetch) -- this is what makes it genuine
                # best-ball, unlike the /lineup/optimize endpoint, which
                # only has season-aggregate stats to work with.
                roster_slots = dict(DEFAULT_ROSTER_SLOTS)
                roster_slots.update(league.roster_slots or {})
                roster_for_optimizer = {
                    pid: {
                        "stats": week_stats.get(pid, {}),
                        "position": player_positions.get(pid, "UNKNOWN"),
                        "name": pid,
                    }
                    for pid in roster_ids
                }
                optimal = calculate_optimal_lineup(
                    roster_for_optimizer, scoring_config,
                    n_qb=roster_slots.get("QB", 0), n_rb=roster_slots.get("RB", 0),
                    n_wr=roster_slots.get("WR", 0), n_te=roster_slots.get("TE", 0),
                    n_flex=roster_slots.get("FLEX", 0), n_superflex=roster_slots.get("SUPERFLEX", 0),
                    n_k=roster_slots.get("K", 0), n_def=roster_slots.get("DEF", 0),
                    n_dl=roster_slots.get("DL", 0), n_lb=roster_slots.get("LB", 0),
                    n_db=roster_slots.get("DB", 0), n_idp_flex=roster_slots.get("IDP_FLEX", 0),
                )
                auto_starter_ids = [a["player_id"] for a in optimal["lineup"]]
                roster_ids = auto_starter_ids

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
            if is_best_ball and auto_starter_ids is not None:
                # Recorded purely for later display (mirrors the
                # coach_bonus/win_bonus/rivalry_bonus precedent) -- never
                # read back for the scoring decision itself, which is
                # recomputed fresh from real per-week stats every call.
                lineup_data["auto_lineup"] = True
                lineup_data["auto_starters"] = auto_starter_ids

        coach_bonus = await _coach_bonus_sum(team.id, "flat_weekly", db)
        if coach_bonus:
            total_score = round(total_score + coach_bonus, 2)
            lineup_data["total"] = total_score
            lineup_data["coach_bonus"] = coach_bonus

        adjustment_total = await _weekly_adjustment_total(team.id, week, year, db)
        if adjustment_total:
            total_score = round(total_score + adjustment_total, 2)
            lineup_data["total"] = total_score
            lineup_data["commissioner_adjustment"] = adjustment_total

        base_totals[team.id] = total_score
        lineup_data_by_team[team.id] = lineup_data

    # Determine this week's matchup winners from BASE totals only -- the
    # exact same comparison get_standings uses (score_a > score_b / tie),
    # just computed here instead of re-derived later, so win_bonus can be
    # applied before the upsert. A tie gets no bonus on either side, same
    # as get_standings never credits a win for one.
    matchups = _effective_matchups(league, teams, week)
    winners: set = set()
    for team_a, team_b in matchups:
        score_a = base_totals.get(team_a, 0.0)
        score_b = base_totals.get(team_b, 0.0)
        if score_a > score_b:
            winners.add(team_a)
        elif score_b > score_a:
            winners.add(team_b)

    # Rivalry Week (Phase 3): a flat bonus for winning this exact week,
    # league-wide (not per-coach, no Coach/_coach_bonus_sum involvement --
    # see DEFAULT_RIVALRY_WEEK_SETTINGS/get_rivalry_week_settings above).
    # Computed once per call, not per team, since it depends only on the
    # league and the week being calculated, not on which team we're
    # looking at.
    rivalry_settings = get_rivalry_week_settings(league)
    rivalry_active_this_week = (
        league.league_type == LeagueType.CONFERENCE
        and rivalry_settings["enabled"]
        and rivalry_settings["week"] == week
    )

    # PASS 2 -- apply win_bonus and (if this is the designated Rivalry
    # Week) the rivalry bonus to this week's actual winners (determined
    # above from base scores, so neither bonus can ever affect who won),
    # then upsert. A team with no win_bonus coach and no active rivalry
    # bonus, or a bye team this week (not in `matchups` at all -- odd
    # team count), just carries its base total through unchanged.
    results = []
    for team in teams:
        total_score = base_totals[team.id]
        lineup_data = lineup_data_by_team[team.id]

        if team.id in winners:
            win_bonus = await _coach_bonus_sum(team.id, "win_bonus", db)
            if win_bonus:
                total_score = round(total_score + win_bonus, 2)
                lineup_data["total"] = total_score
                lineup_data["win_bonus"] = win_bonus

            if rivalry_active_this_week:
                rivalry_bonus = rivalry_settings["bonus_value"]
                if rivalry_bonus:
                    total_score = round(total_score + rivalry_bonus, 2)
                    lineup_data["total"] = total_score
                    lineup_data["rivalry_bonus"] = rivalry_bonus

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


async def get_standings(league_id: str, db: AsyncSession, through_week: int | None = None) -> List[Dict[str, Any]]:
    """
    Get current standings for a league by analyzing weekly scores
    and head-to-head matchups.

    Queries all WeeklyScores for the league, groups by team,
    computes wins/losses/ties from head-to-head comparisons,
    and returns ordered standings.

    through_week: when given, only weeks 1..through_week count -- for
    seeding a playoff bracket off REGULAR SEASON performance only, not
    contaminated by playoff weeks' own scores once they start counting
    too (playoff_service uses this; every other caller leaves it None
    for the existing full-season-to-date behavior, unchanged).

    Returns:
        List of dicts with: team_id, team_name, wins, losses, ties,
        points_for, points_against, conference (None outside conference
        leagues -- grouping by it is left to the caller/frontend so this
        shape stays a flat list for every other consumer)
    """
    # Get all teams for name lookup
    teams_result = await db.execute(
        select(Team).where(Team.league_id == league_id)
    )
    teams = teams_result.scalars().all()
    team_map = {t.id: t.name for t in teams}

    if not teams:
        return []

    # Needed by _effective_matchups (Phase 4, Guillotine finale pairing) --
    # a no-op fetch for the vast majority of leagues, which aren't
    # Guillotine, but cheap enough not to special-case around.
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()

    # Get all weekly scores for this league
    scores_query = select(WeeklyScore).where(WeeklyScore.league_id == league_id)
    if through_week is not None:
        scores_query = scores_query.where(WeeklyScore.week <= through_week)
    scores_result = await db.execute(scores_query)
    all_scores = scores_result.scalars().all()

    if not all_scores:
        # Return teams with zero stats
        return [
            {
                "team_id": t.id,
                "team_name": t.name,
                "conference": t.conference,
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
            "conference": t.conference,
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
    for (year, week), week_scores in weekly_scores.items():
        matchups = _effective_matchups(league, teams, week)
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


DEFAULT_SEASON_WEEKS = 14


async def get_season_schedule(
    league_id: str,
    year: int,
    db: AsyncSession,
    num_weeks: int = DEFAULT_SEASON_WEEKS,
) -> List[Dict[str, Any]]:
    """
    Full-season, week-by-week matchup schedule for a league.

    For a week that already has a real WeeklyScore on record, that actual
    score is used. For a week that hasn't been played/calculated yet, each
    team's score is *projected* as the average of that same team's own
    actual scores from completed weeks earlier in the season -- a simple,
    honest baseline (there's no per-player projection model in this app
    yet). A team with zero completed weeks gets a null projection rather
    than a fabricated number.
    """
    teams_result = await db.execute(select(Team).where(Team.league_id == league_id))
    teams = teams_result.scalars().all()
    team_map = {t.id: t.name for t in teams}
    team_ids = [t.id for t in teams]

    if len(team_ids) < 2:
        return []

    # Needed by _effective_matchups (Phase 4, Guillotine finale pairing).
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()

    scores_result = await db.execute(
        select(WeeklyScore).where(WeeklyScore.league_id == league_id, WeeklyScore.year == year)
    )
    all_scores = scores_result.scalars().all()

    # scores_by_team[team_id][week] = total_score, for O(1) lookups below
    # instead of a query per team per week.
    scores_by_team: Dict[str, Dict[int, float]] = {}
    for ws in all_scores:
        scores_by_team.setdefault(ws.team_id, {})[ws.week] = ws.total_score

    def project(team_id: str, week: int) -> Optional[float]:
        played = [s for w, s in scores_by_team.get(team_id, {}).items() if w < week]
        if not played:
            return None
        return round(sum(played) / len(played), 2)

    def team_entry(team_id: str, week: int) -> Dict[str, Any]:
        actual = scores_by_team.get(team_id, {}).get(week)
        return {
            "id": team_id,
            "name": team_map.get(team_id, "Unknown"),
            "score": actual,
            "projected_score": actual if actual is not None else project(team_id, week),
            "is_projected": actual is None,
        }

    schedule = []
    for week in range(1, num_weeks + 1):
        matchups = _effective_matchups(league, teams, week)
        schedule.append({
            "week": week,
            "matchups": [
                {"team_a": team_entry(a, week), "team_b": team_entry(b, week)}
                for a, b in matchups
            ],
        })

    return schedule


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

    # Needed by _effective_matchups (Phase 4, Guillotine finale pairing).
    league_result = await db.execute(select(League).where(League.id == league_id))
    league = league_result.scalar_one_or_none()

    matchups = _effective_matchups(league, teams, week)

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


async def notify_matchup_results(league_id: str, week: int, year: int, db: AsyncSession) -> None:
    """Notify both teams in every one of this week's matchups whether
    they won, lost, or tied. Closes the last gap the notification
    feature deliberately left open: at the time, there was no reliable
    "this week is truly over" signal to gate a one-time result
    notification on outside of playoff weeks specifically (which have a
    fixed, known week number to compare against the live NFL week).
    Regular-season weeks don't have that fixed-week-number property, but
    they DO have an equivalent signal: the scheduler already knows the
    live week every 2 minutes, so the moment that live week increments
    past this one, this week is exactly as "final" as a playoff round is
    -- see scheduler.py's _last_seen_week tracking, which is what
    actually decides when to call this, once per week, not every tick."""
    matchups = await get_weekly_matchups(league_id, week, year, db)
    if not matchups:
        return

    team_ids = {m["home_team_id"] for m in matchups} | {m["away_team_id"] for m in matchups}
    teams_result = await db.execute(select(Team).where(Team.id.in_(team_ids)))
    teams_by_id = {t.id: t for t in teams_result.scalars().all()}

    # get_weekly_matchups defaults a team with no WeeklyScore row to a
    # score of 0.0 -- fine for display, but here it would read as a real
    # 0-0 tie and notify both teams of a result that never actually
    # happened (e.g. this week's scoring pass failed or hasn't run for
    # this league yet). Only trust a matchup where at least one side has
    # an actual scored row.
    scored_result = await db.execute(
        select(WeeklyScore.team_id).where(
            WeeklyScore.league_id == league_id,
            WeeklyScore.week == week,
            WeeklyScore.year == year,
        )
    )
    scored_team_ids = {row[0] for row in scored_result.all()}

    link = f"/leagues/{league_id}/standings"

    for m in matchups:
        home_team = teams_by_id.get(m["home_team_id"])
        away_team = teams_by_id.get(m["away_team_id"])
        if not home_team or not away_team:
            continue
        if m["home_team_id"] not in scored_team_ids and m["away_team_id"] not in scored_team_ids:
            continue
        home_score, away_score = m["home_score"], m["away_score"]

        if home_score > away_score:
            winner, loser, w_score, l_score = home_team, away_team, home_score, away_score
        elif away_score > home_score:
            winner, loser, w_score, l_score = away_team, home_team, away_score, home_score
        else:
            for team, opp, score in ((home_team, away_team, home_score), (away_team, home_team, away_score)):
                await notify_team_owners(
                    db, team, NotificationType.MATCHUP_TIED,
                    f"You tied {opp.name} {score:g}-{score:g} in week {week}.", league_id, link,
                )
            continue

        await notify_team_owners(
            db, winner, NotificationType.MATCHUP_WON,
            f"You beat {loser.name} {w_score:g}-{l_score:g} in week {week}.", league_id, link,
        )
        await notify_team_owners(
            db, loser, NotificationType.MATCHUP_LOST,
            f"You lost to {winner.name} {l_score:g}-{w_score:g} in week {week}.", league_id, link,
        )

    await db.commit()
