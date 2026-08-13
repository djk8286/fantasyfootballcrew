"""
Tests for Guillotine's schedule/scoring adjustments and elimination
detection (Phase 4, "Guillotine + Custom Twist").

Step 2 (_effective_matchups, this file's first section): the
"stop-scoring slot" binding decision -- an eliminated team's already-
fixed schedule slot just stops producing a win/loss for weeks strictly
after its elimination, and once exactly two Guillotine teams remain
alive, they're force-paired directly every remaining week so the
finale actually plays out head-to-head (the classic round-robin's own
cycle wouldn't otherwise reliably re-pair them every week -- see
_effective_matchups' docstring in standings_service.py).

Step 3 (guillotine_service.process_league_guillotine, this file's
second section): elimination detection, tiebreak, CAS roster dump.

Uses a dedicated 4-team GUILLOTINE fixture (guillotine_seed), not the
shared 3-team `seed` fixture, since exercising "keeps eliminating while
>2 remain, then locks the finale" needs at least 4 teams. All rosters
start empty -- every test controls a team's score for a given week via
a flat_weekly Coach bonus (same trick test_rivalry_week.py/
test_standings_coach_bonus.py use), not real players/stats.
"""
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.models.coach import Coach, CoachPosition
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.standings_service import _effective_matchups, calculate_week, get_standings


def _team(team_id: str, eliminated_week: int | None = None) -> Team:
    """A plain, unpersisted Team -- _effective_matchups only ever reads
    .id/.conference/.eliminated_week, so there's no need to touch the DB
    for the pure schedule-logic tests below."""
    return Team(id=team_id, name=team_id, league_id="league", roster=[],
                roster_version=0, conference=None, eliminated_week=eliminated_week)


def _guillotine_league(league_id: str = "league") -> League:
    return League(id=league_id, name="Guillotine Test", commissioner_id="commish",
                  league_type=LeagueType.GUILLOTINE)


def _standard_league(league_id: str = "league2") -> League:
    return League(id=league_id, name="Standard Test", commissioner_id="commish",
                  league_type=LeagueType.STANDARD)


# ─── Step 2: _effective_matchups ───────────────────────────────────────

def test_drops_pairing_with_earlier_eliminated_team():
    teams = [_team("t1"), _team("t2", eliminated_week=1), _team("t3"), _team("t4")]
    matchups = _effective_matchups(_guillotine_league(), teams, 2)
    ids_in_matchups = {tid for pair in matchups for tid in pair}
    assert "t2" not in ids_in_matchups


def test_keeps_pairing_for_team_eliminated_this_exact_week():
    # t2 is eliminated IN week 2 -- its own last stand still counts as a
    # real matchup for week 2 itself, only weeks after it are dropped.
    teams = [_team("t1"), _team("t2", eliminated_week=2), _team("t3"), _team("t4")]
    matchups = _effective_matchups(_guillotine_league(), teams, 2)
    ids_in_matchups = {tid for pair in matchups for tid in pair}
    assert "t2" in ids_in_matchups


def test_forces_finale_pairing_once_two_alive():
    teams = [_team("t1"), _team("t2", eliminated_week=1), _team("t3", eliminated_week=2), _team("t4")]
    matchups = _effective_matchups(_guillotine_league(), teams, 5)
    # Only t1/t4 are alive -- every other raw pairing that week involves
    # an eliminated team and gets dropped, so this must be the sole
    # matchup, forced if the raw schedule didn't already produce it.
    assert matchups == [("t1", "t4")]


def test_no_finale_force_for_non_guillotine_league():
    """Defensive: proves the finale-pairing override is gated on
    league_type specifically, not just "exactly 2 teams have
    eliminated_week set" -- eliminated_week should never actually be set
    on a non-Guillotine team in practice, but this pins the gate anyway."""
    teams = [_team("t1"), _team("t2", eliminated_week=1), _team("t3", eliminated_week=2), _team("t4")]
    matchups = _effective_matchups(_standard_league(), teams, 5)
    assert matchups == []


def test_effective_matchups_noop_when_nobody_eliminated():
    """Byte-for-byte the same as _build_league_schedule for a league
    where eliminated_week is None on every team (true for every league
    before Step 3 ever runs, and every non-Guillotine league forever)."""
    from app.services.standings_service import _build_league_schedule
    teams = [_team("t1"), _team("t2"), _team("t3"), _team("t4")]
    for week in range(1, 5):
        assert _effective_matchups(_guillotine_league(), teams, week) == _build_league_schedule(teams, week)


# ─── Step 2: DB-integration check (get_standings) ──────────────────────

@pytest_asyncio.fixture
async def guillotine_seed(db_session_factory):
    """4-team GUILLOTINE league (t1..t4), all empty rosters -- score is
    entirely controlled per-test via flat_weekly Coach bonuses."""
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email="gcommish@test.local",
                             username="gcommish", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Guillotine Test League",
                         commissioner_id=commissioner.id, league_type=LeagueType.GUILLOTINE,
                         draft_status=DraftStatus.COMPLETED, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i + 1}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0)
            for i in range(4)
        ]
        db.add_all(teams)
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})

        return {
            "token": token,
            "commissioner_id": commissioner.id,
            "league_id": league.id,
            "team_ids": [t.id for t in teams],
            "db_session_factory": db_session_factory,
        }


async def _add_coach(db_session_factory, team_id, bonus_type, bonus_value, position=CoachPosition.HC):
    async with db_session_factory() as db:
        db.add(Coach(id=str(uuid.uuid4()), name="Test Coach", position=position,
                     team_id=team_id, bonus_type=bonus_type, bonus_value=bonus_value))
        await db.commit()


async def _set_eliminated(db_session_factory, team_id, week):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.eliminated_week = week
        await db.commit()


@pytest.mark.asyncio
async def test_get_standings_stops_crediting_wins_after_elimination(guillotine_seed):
    """With 4 teams (t1..t4) inserted in that order, the round-robin's
    week-1 pairs are (t1,t4)/(t2,t3) and week-2's are (t1,t3)/(t4,t2)
    (verified directly against _build_round_robin_schedule's circle-
    method math). t2 is eliminated after week 1 -- its week-2 raw
    opponent, t4, should get NO matchup at all that week (a bye, not an
    extra unearned win/loss), so t4's record/points_against must stay
    exactly what it was after week 1."""
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _add_coach(db_session_factory, t3, "flat_weekly", 10.0)  # t3 outscores t2 week 1

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})
        standings_after_week1 = {s["team_id"]: s for s in await get_standings(league_id, db)}

    await _set_eliminated(db_session_factory, t2, 1)

    async with db_session_factory() as db:
        await calculate_week(league_id, 2, 2026, db, sleeper_stats={})
        standings_after_week2 = {s["team_id"]: s for s in await get_standings(league_id, db)}

    assert standings_after_week2[t4]["wins"] == standings_after_week1[t4]["wins"]
    assert standings_after_week2[t4]["losses"] == standings_after_week1[t4]["losses"]
    assert standings_after_week2[t4]["ties"] == standings_after_week1[t4]["ties"]
    assert standings_after_week2[t4]["points_against"] == standings_after_week1[t4]["points_against"]

    # t1/t3, whose week-2 pairing doesn't involve the eliminated t2 at
    # all, still get a completely normal week-2 result (proves the skip
    # is scoped to the eliminated team's own pairing, not a blanket
    # freeze of the whole week).
    assert standings_after_week2[t1]["wins"] + standings_after_week2[t1]["losses"] + standings_after_week2[t1]["ties"] == \
        standings_after_week1[t1]["wins"] + standings_after_week1[t1]["losses"] + standings_after_week1[t1]["ties"] + 1
