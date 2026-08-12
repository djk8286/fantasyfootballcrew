"""
Tests for playoff bracket generation and advancement -- pure bracket-math
functions first (no DB), then generate_bracket/try_advance_playoff/
process_league_playoffs against the real async DB fixtures from
conftest.py.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.models.playoff import Playoff, PlayoffMatchup, PlayoffStatus
from app.models.user import User
from app.services.playoff_service import (
    build_seed_slots, total_rounds_for, generate_bracket, try_advance_playoff,
    process_league_playoffs, DEFAULT_PLAYOFF_SETTINGS,
)


# ─── Pure bracket math ─────────────────────────────────────────────


class TestBuildSeedSlots:
    def test_power_of_two_no_byes(self):
        assert build_seed_slots(2) == [1, 2]
        assert build_seed_slots(4) == [1, 4, 2, 3]
        assert build_seed_slots(8) == [1, 8, 4, 5, 2, 7, 3, 6]

    def test_byes_go_to_top_seeds(self):
        # 6 teams -> padded to 8 -> seeds 7,8 don't exist -> whoever's
        # paired with them (1 and 2) gets a bye.
        slots = build_seed_slots(6)
        assert slots == [1, None, 4, 5, 2, None, 3, 6]

    def test_five_teams_three_byes(self):
        slots = build_seed_slots(5)
        assert slots == [1, None, 4, 5, 2, None, 3, None]
        # Seeds 1, 2, 3 (the top 3) get the 3 byes; only 4v5 is a real game.
        real_games = [(slots[i], slots[i + 1]) for i in range(0, 8, 2) if slots[i] and slots[i + 1]]
        assert real_games == [(4, 5)]

    def test_every_real_seed_appears_exactly_once(self):
        for n in range(2, 17):
            slots = build_seed_slots(n)
            real = sorted(s for s in slots if s is not None)
            assert real == list(range(1, n + 1))


class TestTotalRoundsFor:
    def test_various_sizes(self):
        assert total_rounds_for(2) == 1
        assert total_rounds_for(3) == 2  # padded to 4
        assert total_rounds_for(4) == 2
        assert total_rounds_for(5) == 3  # padded to 8
        assert total_rounds_for(6) == 3
        assert total_rounds_for(8) == 3
        assert total_rounds_for(9) == 4  # padded to 16


# ─── generate_bracket / try_advance_playoff (real async DB) ────────


async def _make_league_with_teams(db_session_factory, num_teams=4, league_type=LeagueType.STANDARD,
                                   conferences=None):
    """conferences: optional list of 'A'/'B' assigned to each team in order."""
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4().hex[:8]}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(
            id=str(uuid.uuid4()), name="Playoff Test League", commissioner_id=commissioner.id,
            league_type=league_type, draft_status=DraftStatus.COMPLETED,
            scoring_config={}, roster_slots={},
            playoff_settings={**DEFAULT_PLAYOFF_SETTINGS, "enabled": True, "regular_season_weeks": 2, "num_teams": num_teams},
        )
        db.add(league)
        await db.flush()
        teams = []
        for i in range(num_teams):
            conf = conferences[i] if conferences else None
            t = Team(id=str(uuid.uuid4()), name=f"Team {i+1}", league_id=league.id,
                      owner_id=commissioner.id, roster=[], conference=conf)
            teams.append(t)
        db.add_all(teams)
        await db.commit()
        return league.id, [t.id for t in teams]


async def _add_score(db_session_factory, league_id, team_id, week, score, year=2026):
    async with db_session_factory() as db:
        db.add(WeeklyScore(league_id=league_id, team_id=team_id, week=week, year=year, total_score=score))
        await db.commit()


@pytest.mark.asyncio
async def test_generate_bracket_seeds_by_wins(db_session_factory):
    league_id, (t1, t2, t3, t4) = await _make_league_with_teams(db_session_factory, num_teams=4)
    # Week 1: t1 beats t2 (10-5), t3 beats t4 (10-5)
    # Week 2: t1 beats t3 (10-5), t2 beats t4 (10-5)
    # Records: t1=2-0, t2=1-1, t3=1-1, t4=0-2. t2 vs t3 tied on wins,
    # tiebreak by points_for: t2 = 5+10=15, t3 = 10+5=15 -- also tied,
    # falls through to whatever stable order get_standings produces.
    await _add_score(db_session_factory, league_id, t1, 1, 10)
    await _add_score(db_session_factory, league_id, t2, 1, 5)
    await _add_score(db_session_factory, league_id, t3, 1, 10)
    await _add_score(db_session_factory, league_id, t4, 1, 5)
    await _add_score(db_session_factory, league_id, t1, 2, 10)
    await _add_score(db_session_factory, league_id, t3, 2, 5)
    await _add_score(db_session_factory, league_id, t2, 2, 10)
    await _add_score(db_session_factory, league_id, t4, 2, 5)

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        playoff = await generate_bracket(league, 2026, db)

    assert playoff is not None
    assert playoff.status == PlayoffStatus.IN_PROGRESS
    assert playoff.total_rounds == 2
    seeds = playoff.seeds["combined"]
    assert seeds[0]["team_id"] == t1  # 2-0, clear #1 seed
    assert {s["team_id"] for s in seeds} == {t1, t2, t3, t4}


@pytest.mark.asyncio
async def test_generate_bracket_byes_for_top_seeds(db_session_factory):
    league_id, team_ids = await _make_league_with_teams(db_session_factory, num_teams=6)
    # Give each team a distinct, strictly descending points_for so seeding
    # by "wins" (which falls back to points_for as a tiebreak when every
    # team is 0-0) is deterministic.
    for i, tid in enumerate(team_ids):
        await _add_score(db_session_factory, league_id, tid, 1, 100 - i * 10)

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        playoff = await generate_bracket(league, 2026, db)

        result = await db.execute(select(PlayoffMatchup).where(PlayoffMatchup.playoff_id == playoff.id))
        matchups = {m.slot: m for m in result.scalars().all()}

    seeds = playoff.seeds["combined"]
    seed1_team, seed2_team = seeds[0]["team_id"], seeds[1]["team_id"]

    byes = [m for m in matchups.values() if m.is_bye]
    assert len(byes) == 2
    bye_winners = {m.winner_team_id for m in byes}
    assert bye_winners == {seed1_team, seed2_team}
    # The 2 real round-1 games shouldn't already have a winner.
    real_games = [m for m in matchups.values() if not m.is_bye]
    assert len(real_games) == 2
    assert all(m.winner_team_id is None for m in real_games)


@pytest.mark.asyncio
async def test_generate_bracket_seeds_by_points(db_session_factory):
    league_id, (t1, t2, t3, t4) = await _make_league_with_teams(db_session_factory, num_teams=4)
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.playoff_settings["seeding_method"] = "points"
        await db.commit()

    # t4 has the most total points despite (hypothetically) losing more --
    # points-based seeding should still put t4 first.
    await _add_score(db_session_factory, league_id, t1, 1, 5)
    await _add_score(db_session_factory, league_id, t2, 1, 5)
    await _add_score(db_session_factory, league_id, t3, 1, 5)
    await _add_score(db_session_factory, league_id, t4, 1, 50)

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        playoff = await generate_bracket(league, 2026, db)

    assert playoff.seeds["combined"][0]["team_id"] == t4


@pytest.mark.asyncio
async def test_generate_bracket_separate_conference_brackets(db_session_factory):
    # 2 teams per conference (num_teams=2 in playoff_settings applies
    # PER bracket in "separate" mode -- see playoff_service docstring).
    league_id, team_ids = await _make_league_with_teams(
        db_session_factory, num_teams=4, league_type=LeagueType.CONFERENCE,
        conferences=["A", "A", "B", "B"],
    )
    a1, a2, b1, b2 = team_ids

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.playoff_settings["conference_bracket_mode"] = "separate"
        league.playoff_settings["num_teams"] = 2
        await db.commit()

    for tid in team_ids:
        await _add_score(db_session_factory, league_id, tid, 1, 10)

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        playoff = await generate_bracket(league, 2026, db)

        result = await db.execute(select(PlayoffMatchup).where(PlayoffMatchup.playoff_id == playoff.id))
        matchups = result.scalars().all()

    assert set(playoff.seeds.keys()) == {"A", "B"}
    assert {e["team_id"] for e in playoff.seeds["A"]} == {a1, a2}
    assert {e["team_id"] for e in playoff.seeds["B"]} == {b1, b2}
    assert {m.bracket for m in matchups} == {"A", "B"}
    # Each bracket's own matchup should only involve teams from that conference.
    a_matchup = next(m for m in matchups if m.bracket == "A")
    assert {a_matchup.team_a_id, a_matchup.team_b_id} == {a1, a2}
    b_matchup = next(m for m in matchups if m.bracket == "B")
    assert {b_matchup.team_a_id, b_matchup.team_b_id} == {b1, b2}


@pytest.mark.asyncio
async def test_try_advance_playoff_waits_for_week_to_pass(db_session_factory):
    league_id, (t1, t2) = await _make_league_with_teams(db_session_factory, num_teams=2)
    for tid, score in [(t1, 20), (t2, 10)]:
        await _add_score(db_session_factory, league_id, tid, 3, score)  # start_week = regular_season_weeks(2)+1 = 3

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        playoff = await generate_bracket(league, 2026, db)
        assert playoff.total_rounds == 1

        # Live week still ON the matchup's week -- not over yet.
        await try_advance_playoff(playoff, live_week=3, db=db)
        result = await db.execute(select(PlayoffMatchup).where(PlayoffMatchup.playoff_id == playoff.id))
        m = result.scalars().one()
        assert m.winner_team_id is None

        # Live week has now passed -- resolve it.
        await try_advance_playoff(playoff, live_week=4, db=db)
        await db.refresh(playoff)
        result = await db.execute(select(PlayoffMatchup).where(PlayoffMatchup.playoff_id == playoff.id))
        m = result.scalars().one()
        assert m.winner_team_id == t1  # higher score
        assert playoff.status == PlayoffStatus.COMPLETED  # single-round bracket


@pytest.mark.asyncio
async def test_try_advance_playoff_builds_next_round(db_session_factory):
    league_id, team_ids = await _make_league_with_teams(db_session_factory, num_teams=4)
    t1, t2, t3, t4 = team_ids
    # Seed by points_for (all 0-0 on wins): higher score = better seed.
    for tid, score in zip(team_ids, [40, 30, 20, 10]):
        await _add_score(db_session_factory, league_id, tid, 1, score)

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        playoff = await generate_bracket(league, 2026, db)  # seeds: t1,t2,t3,t4 -> round1: t1v t4, t2 v t3

    # Round 1 (week 3): t1 beats t4, t3 beats t2 (an upset).
    await _add_score(db_session_factory, league_id, t1, 3, 100)
    await _add_score(db_session_factory, league_id, t4, 3, 10)
    await _add_score(db_session_factory, league_id, t2, 3, 10)
    await _add_score(db_session_factory, league_id, t3, 3, 100)

    async with db_session_factory() as db:
        result = await db.execute(select(Playoff).where(Playoff.id == playoff.id))
        playoff = result.scalar_one()
        await try_advance_playoff(playoff, live_week=4, db=db)
        await db.refresh(playoff)

        assert playoff.current_round == 2
        assert playoff.status == PlayoffStatus.IN_PROGRESS

        result = await db.execute(select(PlayoffMatchup).where(PlayoffMatchup.playoff_id == playoff.id, PlayoffMatchup.round == 2))
        final = result.scalars().one()
        assert {final.team_a_id, final.team_b_id} == {t1, t3}  # the two round-1 winners
        assert final.week == 4


@pytest.mark.asyncio
async def test_process_league_playoffs_waits_for_regular_season_to_end(db_session_factory):
    league_id, team_ids = await _make_league_with_teams(db_session_factory, num_teams=2)
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        # regular_season_weeks == 2 -- live week 2 is still IN the regular season.
        await process_league_playoffs(league, 2026, live_week=2, db=db)
        result = await db.execute(select(Playoff).where(Playoff.league_id == league_id))
        assert result.scalar_one_or_none() is None

        # live week 3 -- regular season is over, should generate now.
        await process_league_playoffs(league, 2026, live_week=3, db=db)
        result = await db.execute(select(Playoff).where(Playoff.league_id == league_id))
        assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_process_league_playoffs_noop_when_disabled(db_session_factory):
    league_id, team_ids = await _make_league_with_teams(db_session_factory, num_teams=2)
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.playoff_settings["enabled"] = False
        await db.commit()

        await process_league_playoffs(league, 2026, live_week=10, db=db)
        result = await db.execute(select(Playoff).where(Playoff.league_id == league_id))
        assert result.scalar_one_or_none() is None
