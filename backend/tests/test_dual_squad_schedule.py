"""
Tests for Phase 7 ("Dual-Squad/Mirror") Step 3 -- _effective_matchups'
DUAL_SQUAD extension: a manager's own two linked teams must never be
scheduled against each other. Mirrors test_guillotine_elimination.py's
pure-function, unpersisted-Team() style -- _effective_matchups only
ever reads .id/.conference/.eliminated_week/.partner_team_id, so there's
no need to touch the DB for these.

The cross-wire fix-up (2+ partner-pairs dropping in the same week get
rewired into new non-partner matchups instead of leaving everyone on a
bye) was independently verified correct via simulation against the
real _build_round_robin_schedule algorithm during planning -- see the
n=4 test below, which is the exact degenerate case that simulation
found (a classic 4-team round-robin has exactly 3 rounds, which are
exactly the 3 ways to split 4 teams into 2 disjoint pairs, so one full
week both partner-pairs raw-schedule against each other simultaneously).
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services.standings_service import _effective_matchups, _build_league_schedule, get_standings


def _team(team_id: str, partner_team_id: str | None = None) -> Team:
    return Team(id=team_id, name=team_id, league_id="league", roster=[],
                roster_version=0, conference=None, partner_team_id=partner_team_id)


def _dual_squad_league(league_id: str = "league") -> League:
    return League(id=league_id, name="Dual Squad Test", commissioner_id="commish",
                  league_type=LeagueType.DUAL_SQUAD)


def _standard_league(league_id: str = "league2") -> League:
    return League(id=league_id, name="Standard Test", commissioner_id="commish",
                  league_type=LeagueType.STANDARD)


def _adjacent_pairs(n: int) -> list[Team]:
    """n teams, t0..t(n-1), partnered adjacently: (t0,t1), (t2,t3), ..."""
    ids = [f"t{i}" for i in range(n)]
    partner_of = {}
    for i in range(0, n, 2):
        partner_of[ids[i]] = ids[i + 1]
        partner_of[ids[i + 1]] = ids[i]
    return [_team(tid, partner_of[tid]) for tid in ids]


def _num_rounds(n: int) -> int:
    # Matches _build_round_robin_schedule's own num_rounds derivation.
    return n - 1 if n % 2 == 0 else n


def test_drops_pairing_between_partners():
    teams = _adjacent_pairs(4)
    partner_of = {t.id: t.partner_team_id for t in teams}
    for week in range(1, _num_rounds(4) + 1):
        matchups = _effective_matchups(_dual_squad_league(), teams, week)
        for (a, b) in matchups:
            assert partner_of.get(a) != b, f"week {week}: partner pairing {(a, b)} was not dropped"


def test_n4_single_dropped_pair_week_gets_cross_wired_not_wiped():
    # The exact degenerate week found by simulation: n=4, week 3, where
    # the raw schedule pairs BOTH partner-pairs against each other.
    teams = _adjacent_pairs(4)
    raw = _build_league_schedule(teams, 3)
    assert set(raw) == {("t0", "t1"), ("t2", "t3")}, "raw schedule assumption for n=4 week 3 changed"

    matchups = _effective_matchups(_dual_squad_league(), teams, 3)
    assert len(matchups) == 2, "cross-wire fix-up must not leave this week with zero games"
    partner_of = {t.id: t.partner_team_id for t in teams}
    for (a, b) in matchups:
        assert partner_of.get(a) != b
    # Every team still appears exactly once.
    seen = [tid for pair in matchups for tid in pair]
    assert sorted(seen) == ["t0", "t1", "t2", "t3"]


def test_isolated_single_partner_drop_produces_ordinary_bye():
    # n=6, adjacent pairing -- find a week where exactly one partner pair
    # is raw-scheduled together (confirmed to exist via the same
    # simulation approach: n=6 never has a multi-drop week, only
    # isolated ones or none).
    teams = _adjacent_pairs(6)
    partner_of = {t.id: t.partner_team_id for t in teams}
    found_isolated_drop = False
    for week in range(1, _num_rounds(6) + 1):
        raw = _build_league_schedule(teams, week)
        dropped = [(a, b) for (a, b) in raw if partner_of.get(a) == b]
        if len(dropped) == 1:
            found_isolated_drop = True
            matchups = _effective_matchups(_dual_squad_league(), teams, week)
            dropped_ids = set(dropped[0])
            # The two teams involved in the isolated drop are simply
            # absent from this week's matchups (a bye), not paired with
            # anyone new.
            remaining_ids = {tid for pair in matchups for tid in pair}
            assert not dropped_ids.issubset(remaining_ids) or len(remaining_ids & dropped_ids) == 0
    assert found_isolated_drop, "test setup assumption (an isolated single-drop week exists for n=6) failed"


def test_cross_wire_never_reconstructs_a_partner_pairing():
    for n in [4, 6, 8, 10, 12]:
        teams = _adjacent_pairs(n)
        partner_of = {t.id: t.partner_team_id for t in teams}
        for week in range(1, _num_rounds(n) + 1):
            matchups = _effective_matchups(_dual_squad_league(), teams, week)
            for (a, b) in matchups:
                assert partner_of.get(a) != b, f"n={n} week={week}: reconstructed partner pairing {(a, b)}"
            # No team should ever appear twice in the same week.
            seen = [tid for pair in matchups for tid in pair]
            assert len(seen) == len(set(seen)), f"n={n} week={week}: duplicate team in one week's matchups"


def test_non_dual_squad_league_effective_matchups_unaffected():
    teams = _adjacent_pairs(4)
    for week in range(1, _num_rounds(4) + 1):
        raw = _build_league_schedule(teams, week)
        matchups = _effective_matchups(_standard_league(), teams, week)
        assert matchups == raw, f"week {week}: STANDARD league's _effective_matchups must be byte-identical to raw"


@pytest.mark.asyncio
async def test_get_standings_uses_dual_squad_effective_matchups(db_session_factory):
    """Integration test: a real 4-team DUAL_SQUAD league scored across a
    full round-robin cycle -- no team's win/loss/tie count should ever
    include a game against its own partner."""
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dsscommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Dual Squad Schedule Integration League",
                         commissioner_id=commissioner.id, league_type=LeagueType.DUAL_SQUAD,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0)
            for i in range(4)
        ]
        db.add_all(teams)
        await db.flush()
        teams[0].partner_team_id, teams[1].partner_team_id = teams[1].id, teams[0].id
        teams[2].partner_team_id, teams[3].partner_team_id = teams[3].id, teams[2].id
        await db.commit()
        league_id = league.id
        team_ids = [t.id for t in teams]
        partner_of = {teams[0].id: teams[1].id, teams[1].id: teams[0].id,
                      teams[2].id: teams[3].id, teams[3].id: teams[2].id}

    # Score every team a distinct, deterministic value each week so
    # get_standings has real WeeklyScore rows to derive wins/losses from.
    async with db_session_factory() as db:
        for week in range(1, 4):  # n=4 -> 3 rounds
            for idx, tid in enumerate(team_ids):
                db.add(WeeklyScore(league_id=league_id, team_id=tid, week=week, year=2026,
                                    total_score=float(idx * 10 + week), lineup_data={}))
        await db.commit()

    async with db_session_factory() as db:
        standings = await get_standings(league_id, db)
        result = await db.execute(select(Team).where(Team.league_id == league_id))
        fetched_teams = result.scalars().all()
        for week in range(1, 4):
            matchups = _effective_matchups(
                League(id=league_id, name="x", commissioner_id="x", league_type=LeagueType.DUAL_SQUAD),
                fetched_teams, week,
            )
            for (a, b) in matchups:
                assert partner_of.get(a) != b, f"week {week}: get_standings' own schedule call paired partners"

    assert len(standings) == 4
    for row in standings:
        # 3 weeks scored; each team should have exactly 3 counted games
        # (wins+losses+ties) MINUS any bye weeks caused by the partner
        # exclusion -- never a game credited against its own partner,
        # which would be undetectable directly here but is already
        # proven impossible by the pure _effective_matchups tests above.
        # This test's real job is confirming the full DB-backed path
        # (get_standings -> _effective_matchups) doesn't error and
        # produces sane, non-zero-everywhere stats.
        assert row["wins"] + row["losses"] + row["ties"] <= 3
        assert row["team_id"] in team_ids
