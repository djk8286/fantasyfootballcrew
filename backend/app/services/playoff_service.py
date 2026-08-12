"""
Playoff bracket generation and advancement.

Entirely opt-in per league (League.playoff_settings["enabled"], default
False) and entirely automatic once turned on -- no commissioner action
needed to generate or advance the bracket, matching the "no manual step"
spirit the auto weekly-scoring feature already established this session.
Driven by the scheduler (see scheduler.py's _advance_playoffs_once),
which already fetches Sleeper's live NFL week every 2 minutes during the
season -- that live week is this module's only concept of "is this round
actually over yet", passed in by the caller rather than fetched here, to
keep this module free of any network/Sleeper dependency of its own.

Bracket structure: a standard single-elimination bracket, seeded so the
top seeds can only meet as late as possible (1 and 2 can only meet in
the final) -- the same algorithm real seeded tournaments use. Padded
with byes up to the next power of 2 when the team count isn't one
already; byes go to the top seeds, resolved immediately at generation
time rather than waiting for a "round" to complete.
"""
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.models.playoff import Playoff, PlayoffMatchup, PlayoffStatus
from app.services.standings_service import get_standings

DEFAULT_PLAYOFF_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "regular_season_weeks": 13,
    "num_teams": 6,
    "seeding_method": "wins",  # "wins" | "points"
    "conference_bracket_mode": "combined",  # "combined" | "separate" -- only used for CONFERENCE leagues
}


def get_playoff_settings(league: League) -> dict[str, Any]:
    merged = dict(DEFAULT_PLAYOFF_SETTINGS)
    merged.update(league.playoff_settings or {})
    return merged


def _seed_order(bracket_size: int) -> list[int]:
    """The classic recursive seeded-bracket ordering: adjacent pairs in
    the returned list are round-1 matchups, arranged so seed 1 and seed 2
    can only meet in the final. bracket_size must be a power of 2."""
    order = [1]
    k = 1
    while k < bracket_size:
        order = [x for s in order for x in (s, 2 * k + 1 - s)]
        k *= 2
    return order


def build_seed_slots(num_teams: int) -> list[int | None]:
    """num_teams real seeds (1..num_teams), padded with None (bye) up to
    the next power of 2, in standard bracket order."""
    if num_teams < 1:
        return []
    bracket_size = 1
    while bracket_size < num_teams:
        bracket_size *= 2
    return [s if s <= num_teams else None for s in _seed_order(bracket_size)]


def total_rounds_for(num_teams: int) -> int:
    bracket_size = 1
    while bracket_size < max(num_teams, 1):
        bracket_size *= 2
    return bracket_size.bit_length() - 1 if bracket_size > 1 else 0


def _build_round1_matchups(seed_team_ids: list[str], bracket_label: str, week: int) -> list[dict]:
    """seed_team_ids: ordered best-to-worst, index 0 = seed 1."""
    num_teams = len(seed_team_ids)
    slots = build_seed_slots(num_teams)
    team_by_seed = {i + 1: seed_team_ids[i] for i in range(num_teams)}
    matchups = []
    for i in range(0, len(slots), 2):
        team_a = team_by_seed.get(slots[i]) if slots[i] else None
        team_b = team_by_seed.get(slots[i + 1]) if slots[i + 1] else None
        is_bye = (team_a is None) != (team_b is None)  # exactly one side missing
        matchups.append({
            "bracket": bracket_label,
            "round": 1,
            "slot": i // 2,
            "week": week,
            "team_a_id": team_a,
            "team_b_id": team_b,
            "is_bye": is_bye,
            "winner_team_id": (team_a or team_b) if is_bye else None,
        })
    return matchups


async def _seed_standings(league_id: str, db: AsyncSession, through_week: int, seeding_method: str,
                           conference: str | None = None) -> list[dict]:
    standings = await get_standings(league_id, db, through_week=through_week)
    if conference is not None:
        standings = [s for s in standings if s["conference"] == conference]
    if seeding_method == "points":
        standings = sorted(standings, key=lambda s: s["points_for"], reverse=True)
    # "wins" -- get_standings already sorts (wins desc, points_for desc)
    return standings


async def generate_bracket(league: League, year: int, db: AsyncSession) -> Playoff | None:
    """Creates the Playoff + round-1 PlayoffMatchup rows. Returns None if
    there aren't enough teams to actually run a bracket (fewer than 2)."""
    settings = get_playoff_settings(league)
    num_teams = settings["num_teams"]
    seeding_method = settings["seeding_method"]
    regular_season_weeks = settings["regular_season_weeks"]
    start_week = regular_season_weeks + 1
    is_separate = league.league_type == LeagueType.CONFERENCE and settings.get("conference_bracket_mode") == "separate"

    all_matchup_rows: list[dict] = []
    seeds_snapshot: dict[str, list[dict]] = {}

    if is_separate:
        for conf in ("A", "B"):
            standings = await _seed_standings(league.id, db, regular_season_weeks, seeding_method, conference=conf)
            picked = standings[:num_teams]
            if len(picked) < 2:
                continue
            seeds_snapshot[conf] = [{"team_id": s["team_id"], "seed": i + 1} for i, s in enumerate(picked)]
            all_matchup_rows += _build_round1_matchups([s["team_id"] for s in picked], conf, start_week)
        rounds = total_rounds_for(max((len(v) for v in seeds_snapshot.values()), default=0))
    else:
        standings = await _seed_standings(league.id, db, regular_season_weeks, seeding_method, conference=None)
        picked = standings[:num_teams]
        if len(picked) < 2:
            return None
        seeds_snapshot["combined"] = [{"team_id": s["team_id"], "seed": i + 1} for i, s in enumerate(picked)]
        all_matchup_rows = _build_round1_matchups([s["team_id"] for s in picked], "combined", start_week)
        rounds = total_rounds_for(len(picked))

    if not all_matchup_rows:
        return None

    playoff = Playoff(
        league_id=league.id, year=year, seeding_method=seeding_method,
        conference_bracket_mode=settings.get("conference_bracket_mode") if league.league_type == LeagueType.CONFERENCE else None,
        seeds=seeds_snapshot, status=PlayoffStatus.IN_PROGRESS,
        start_week=start_week, total_rounds=rounds, current_round=1,
    )
    db.add(playoff)
    await db.flush()
    for row in all_matchup_rows:
        db.add(PlayoffMatchup(playoff_id=playoff.id, **row))
    await db.commit()
    await db.refresh(playoff)
    return playoff


async def try_advance_playoff(playoff: Playoff, live_week: int, db: AsyncSession) -> None:
    """Resolves any of the current round's still-open real matchups whose
    week is now in the past (live_week > matchup.week -- i.e. actually
    over, not just "scores calculated so far mid-week"), then, once every
    matchup in the round has a winner, either builds the next round or
    marks the playoff COMPLETED if this was the final one. Safe to call
    repeatedly (every scheduler tick) -- a no-op once nothing's changed."""
    result = await db.execute(
        select(PlayoffMatchup).where(PlayoffMatchup.playoff_id == playoff.id, PlayoffMatchup.round == playoff.current_round)
    )
    current_matchups = list(result.scalars().all())

    for m in current_matchups:
        if m.winner_team_id is not None or m.is_bye:
            continue
        if live_week <= m.week:
            continue  # this round's games haven't finished yet
        score_result = await db.execute(
            select(WeeklyScore).where(
                WeeklyScore.league_id == playoff.league_id, WeeklyScore.week == m.week,
                WeeklyScore.team_id.in_([m.team_a_id, m.team_b_id]),
            )
        )
        scores = {ws.team_id: ws.total_score for ws in score_result.scalars().all()}
        score_a = scores.get(m.team_a_id, 0.0)
        score_b = scores.get(m.team_b_id, 0.0)
        # Ties go to team_a -- in round 1 that's always the better seed
        # (see _build_round1_matchups); in later rounds it's whichever
        # source matchup was earlier in bracket order. An exact tie in a
        # fantasy matchup is rare enough that a simple, deterministic
        # rule beats not having one at all.
        m.winner_team_id = m.team_a_id if score_a >= score_b else m.team_b_id

    if any(m.winner_team_id is None for m in current_matchups):
        return  # still waiting on at least one real matchup

    if playoff.current_round >= playoff.total_rounds:
        playoff.status = PlayoffStatus.COMPLETED
        await db.commit()
        return

    # Build the next round: consecutive matchups (by bracket, by slot)
    # collapse pairwise, same convention _build_round1_matchups already
    # establishes for round 1.
    next_week = max(m.week for m in current_matchups) + 1
    by_bracket: dict[str, list[PlayoffMatchup]] = {}
    for m in sorted(current_matchups, key=lambda x: x.slot):
        by_bracket.setdefault(m.bracket, []).append(m)

    for bracket_label, matchups in by_bracket.items():
        for i in range(0, len(matchups), 2):
            if i + 1 >= len(matchups):
                continue  # odd one out (shouldn't happen with power-of-2 bracket sizing)
            team_a = matchups[i].winner_team_id
            team_b = matchups[i + 1].winner_team_id
            db.add(PlayoffMatchup(
                playoff_id=playoff.id, bracket=bracket_label, round=playoff.current_round + 1,
                slot=i // 2, week=next_week, team_a_id=team_a, team_b_id=team_b, is_bye=False,
            ))

    playoff.current_round += 1
    await db.commit()


async def process_league_playoffs(league: League, year: int, live_week: int, db: AsyncSession) -> None:
    """One league's worth of the scheduler's per-tick playoff work:
    generate the bracket the first time live_week passes
    regular_season_weeks, or advance an already-generated one. A no-op
    for a league with playoffs disabled, or where it's neither time to
    generate nor anything left to advance."""
    settings = get_playoff_settings(league)
    if not settings.get("enabled"):
        return
    regular_season_weeks = settings["regular_season_weeks"]
    if live_week <= regular_season_weeks:
        return  # regular season still in progress -- nothing to do yet

    result = await db.execute(select(Playoff).where(Playoff.league_id == league.id, Playoff.year == year))
    playoff = result.scalar_one_or_none()

    if not playoff:
        await generate_bracket(league, year, db)
        return

    if playoff.status == PlayoffStatus.IN_PROGRESS:
        await try_advance_playoff(playoff, live_week, db)
