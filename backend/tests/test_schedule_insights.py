"""
Tests for AI Co-Commissioner v1 Phase 2 Step 3 --
schedule_insights_service.compute_strength_of_schedule (pure
arithmetic, zero LLM calls, no mocking needed -- same testing style as
test_league_health.py/test_scoring_insights.py), plus the
GET /leagues/{id}/commissioner/schedule-insights endpoint.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.schedule_insights_service import compute_strength_of_schedule

YEAR = 2026


async def _make_league(db_session_factory, league_type=LeagueType.STANDARD, extra_kwargs=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"sosschedcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        kwargs = {"scoring_config": {}, "roster_slots": {}, **(extra_kwargs or {})}
        league = League(id=str(uuid.uuid4()), name="SOS Test League", commissioner_id=commissioner.id,
                         league_type=league_type, **kwargs)
        db.add(league)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"league_id": league.id, "commissioner_id": commissioner.id, "token": token}


async def _add_team(db_session_factory, league_id, name=None, eliminated_week=None, partner_team_id=None):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name=name or f"Team {uuid.uuid4().hex[:6]}", league_id=league_id,
                    roster=[], roster_version=0, eliminated_week=eliminated_week, partner_team_id=partner_team_id)
        db.add(team)
        await db.commit()
        return team.id


async def _set_partner(db_session_factory, team_id, partner_id):
    async with db_session_factory() as db:
        team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one()
        team.partner_team_id = partner_id
        await db.commit()


async def _add_weekly_score(db_session_factory, league_id, team_id, week, total_score, year=YEAR):
    async with db_session_factory() as db:
        db.add(WeeklyScore(league_id=league_id, team_id=team_id, week=week, year=year, total_score=total_score))
        await db.commit()


@pytest.mark.asyncio
async def test_identifies_played_vs_remaining_weeks(db_session_factory):
    setup = await _make_league(db_session_factory)
    a = await _add_team(db_session_factory, setup["league_id"], name="A")
    b = await _add_team(db_session_factory, setup["league_id"], name="B")
    # Weeks 1-2 played -> remaining should start at week 3.
    await _add_weekly_score(db_session_factory, setup["league_id"], a, 1, 100.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], b, 1, 90.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], a, 2, 100.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], b, 2, 90.0)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        sos = await compute_strength_of_schedule(league, db)

    assert sos["available"] is True
    assert sos["remaining_weeks"][0] == 3


@pytest.mark.asyncio
async def test_opponent_strength_averaging_correct(db_session_factory):
    setup = await _make_league(db_session_factory)
    strong = await _add_team(db_session_factory, setup["league_id"], name="Strong")
    weak = await _add_team(db_session_factory, setup["league_id"], name="Weak")

    # 1 played week establishes standings: strong averages 150/game,
    # weak averages 50/game.
    await _add_weekly_score(db_session_factory, setup["league_id"], strong, 1, 150.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], weak, 1, 50.0)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        sos = await compute_strength_of_schedule(league, db)

    by_id = {t["team_id"]: t for t in sos["teams"]}
    # weak's only remaining opponent every week is strong (150/game) --
    # weak's sos_score should reflect strong's actual average, not weak's own.
    assert by_id[weak]["sos_score"] == 150.0
    assert by_id[strong]["sos_score"] == 50.0


@pytest.mark.asyncio
async def test_guillotine_eliminated_team_has_no_remaining_schedule(db_session_factory):
    setup = await _make_league(db_session_factory, league_type=LeagueType.GUILLOTINE)
    alive1 = await _add_team(db_session_factory, setup["league_id"], name="Alive1")
    alive2 = await _add_team(db_session_factory, setup["league_id"], name="Alive2")
    alive3 = await _add_team(db_session_factory, setup["league_id"], name="Alive3")
    eliminated = await _add_team(db_session_factory, setup["league_id"], name="Eliminated", eliminated_week=1)
    for tid in (alive1, alive2, alive3, eliminated):
        await _add_weekly_score(db_session_factory, setup["league_id"], tid, 1, 100.0)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        sos = await compute_strength_of_schedule(league, db)

    team_ids_in_output = {t["team_id"] for t in sos["teams"]}
    assert eliminated not in team_ids_in_output
    assert alive1 in team_ids_in_output


@pytest.mark.asyncio
async def test_guillotine_finale_of_two_reports_degenerate_case(db_session_factory):
    setup = await _make_league(db_session_factory, league_type=LeagueType.GUILLOTINE)
    finalist1 = await _add_team(db_session_factory, setup["league_id"], name="Finalist1")
    finalist2 = await _add_team(db_session_factory, setup["league_id"], name="Finalist2")
    await _add_weekly_score(db_session_factory, setup["league_id"], finalist1, 1, 100.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], finalist2, 1, 90.0)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        sos = await compute_strength_of_schedule(league, db)

    assert sos["available"] is True
    assert sos["finale"] is True
    assert sos["teams"] == []
    assert "Finalist1" in sos["summary"] and "Finalist2" in sos["summary"]


@pytest.mark.asyncio
async def test_dual_squad_uses_combined_pair_strength(db_session_factory):
    setup = await _make_league(db_session_factory, league_type=LeagueType.DUAL_SQUAD)
    # Pair 1 (weak individually, strong combined): a1 + a2.
    a1 = await _add_team(db_session_factory, setup["league_id"], name="A1")
    a2 = await _add_team(db_session_factory, setup["league_id"], name="A2")
    await _set_partner(db_session_factory, a1, a2)
    await _set_partner(db_session_factory, a2, a1)
    # Pair 2: b1 + b2.
    b1 = await _add_team(db_session_factory, setup["league_id"], name="B1")
    b2 = await _add_team(db_session_factory, setup["league_id"], name="B2")
    await _set_partner(db_session_factory, b1, b2)
    await _set_partner(db_session_factory, b2, b1)

    # Pair A combined = 50+50=100/game per team-pair-week; Pair B combined = 10+10=20.
    for tid, score in ((a1, 50.0), (a2, 50.0), (b1, 10.0), (b2, 10.0)):
        await _add_weekly_score(db_session_factory, setup["league_id"], tid, 1, score)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        sos = await compute_strength_of_schedule(league, db)

    by_id = {t["team_id"]: t for t in sos["teams"]}
    # Whatever individual opponent a1/a2 face from pair B, that
    # opponent's sos strength value must be pair B's COMBINED average
    # (20.0), not that one individual b-teammate's own 10.0.
    for team_id in (a1, a2):
        assert by_id[team_id]["sos_score"] == 20.0
    for team_id in (b1, b2):
        assert by_id[team_id]["sos_score"] == 100.0


@pytest.mark.asyncio
async def test_schedule_insights_endpoint_commissioner_only(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    a = await _add_team(db_session_factory, setup["league_id"], name="A")
    b = await _add_team(db_session_factory, setup["league_id"], name="B")
    await _add_weekly_score(db_session_factory, setup["league_id"], a, 1, 100.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], b, 1, 90.0)

    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"sosoutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/schedule-insights")
    assert r.status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/schedule-insights")
    assert r.status_code == 200
    assert r.json()["available"] is True
