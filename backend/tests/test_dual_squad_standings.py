"""
Tests for Phase 7 ("Dual-Squad/Mirror") Step 4 -- combined standings.
get_combined_standings is a pure aggregation over get_standings' own
flat output; the /standings/combined endpoint wraps it with a
DUAL_SQUAD-only gate.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.standings_service import get_combined_standings


async def _make_dual_squad_league(db_session_factory, num_teams=4):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dsscommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Dual Squad Standings Test League",
                         commissioner_id=commissioner.id, league_type=LeagueType.DUAL_SQUAD,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0)
            for i in range(num_teams)
        ]
        db.add_all(teams)
        await db.flush()
        for i in range(0, num_teams, 2):
            teams[i].partner_team_id = teams[i + 1].id
            teams[i + 1].partner_team_id = teams[i].id
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"token": token, "league_id": league.id, "team_ids": [t.id for t in teams],
                "db_session_factory": db_session_factory}


@pytest.mark.asyncio
async def test_get_combined_standings_sums_pair_stats(db_session_factory):
    setup = await _make_dual_squad_league(db_session_factory)
    league_id = setup["league_id"]
    t0, t1, t2, t3 = setup["team_ids"]

    async with db_session_factory() as db:
        # Week 1: t0 beats t2 (10 vs 5), t1 beats t3 (8 vs 3)
        for tid, score in [(t0, 10.0), (t2, 5.0), (t1, 8.0), (t3, 3.0)]:
            db.add(WeeklyScore(league_id=league_id, team_id=tid, week=1, year=2026, total_score=score, lineup_data={}))
        await db.commit()

    async with db_session_factory() as db:
        combined = await get_combined_standings(league_id, db)

    pair_01 = next(r for r in combined if set(r["team_ids"]) == {t0, t1})
    pair_23 = next(r for r in combined if set(r["team_ids"]) == {t2, t3})

    assert pair_01["wins"] == 2  # both t0 and t1 won their matchups
    assert pair_01["losses"] == 0
    assert pair_01["points_for"] == 18.0  # 10 + 8
    assert pair_23["wins"] == 0
    assert pair_23["losses"] == 2
    assert pair_23["points_for"] == 8.0  # 5 + 3


@pytest.mark.asyncio
async def test_get_combined_standings_sorted_by_wins_then_points(db_session_factory):
    setup = await _make_dual_squad_league(db_session_factory)
    league_id = setup["league_id"]
    t0, t1, t2, t3 = setup["team_ids"]

    async with db_session_factory() as db:
        # Pair (t0,t1) wins both its games; pair (t2,t3) loses both.
        for tid, score in [(t0, 10.0), (t2, 5.0), (t1, 8.0), (t3, 3.0)]:
            db.add(WeeklyScore(league_id=league_id, team_id=tid, week=1, year=2026, total_score=score, lineup_data={}))
        await db.commit()

    async with db_session_factory() as db:
        combined = await get_combined_standings(league_id, db)

    assert len(combined) == 2
    # Sorted wins-desc-then-points_for-desc, same as get_standings' own sort.
    assert combined[0]["wins"] >= combined[1]["wins"]
    assert set(combined[0]["team_ids"]) == {t0, t1}


@pytest.mark.asyncio
async def test_get_combined_standings_orphan_team_returns_single_row(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dssorphan{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Orphan League", commissioner_id=commissioner.id,
                         league_type=LeagueType.DUAL_SQUAD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        a = Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id, owner_id=commissioner.id, roster=[], roster_version=0)
        b = Team(id=str(uuid.uuid4()), name="Team B (orphan)", league_id=league.id, owner_id=commissioner.id, roster=[], roster_version=0)
        db.add_all([a, b])
        await db.flush()
        # a has no partner set -- b is an orphan too (neither linked)
        await db.commit()
        league_id = league.id
        a_id, b_id = a.id, b.id

    async with db_session_factory() as db:
        combined = await get_combined_standings(league_id, db)

    assert len(combined) == 2
    for row in combined:
        assert len(row["team_ids"]) == 1


@pytest.mark.asyncio
async def test_get_combined_standings_empty_league_returns_empty_list(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dssempty{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Empty League", commissioner_id=commissioner.id,
                         league_type=LeagueType.DUAL_SQUAD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        league_id = league.id

    async with db_session_factory() as db:
        combined = await get_combined_standings(league_id, db)
    assert combined == []


@pytest.mark.asyncio
async def test_combined_standings_endpoint_404s_for_non_dual_squad_league(client, db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dssstandard{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Standard League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        league_id = league.id

    r = await client.get(f"/leagues/{league_id}/standings/combined")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_combined_standings_endpoint_matches_service_helper(client, db_session_factory):
    setup = await _make_dual_squad_league(db_session_factory)
    league_id = setup["league_id"]

    async with db_session_factory() as db:
        direct = await get_combined_standings(league_id, db)

    r = await client.get(f"/leagues/{league_id}/standings/combined")
    assert r.status_code == 200
    assert r.json()["combined_standings"] == direct
