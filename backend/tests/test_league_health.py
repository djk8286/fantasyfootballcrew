"""
Tests for AI Co-Commissioner v1 Step 6 -- league_health_service.py:
compute_league_health (pure arithmetic over existing Lineup/Transaction/
WeeklyScore rows, zero LLM calls -- no mocking needed at all, unlike
every other AI-adjacent service in this codebase) and the
GET /leagues/{id}/commissioner/health endpoint.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.lineup import Lineup
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.league_health_service import compute_league_health, AT_RISK_LINEUP_RATE

YEAR = 2026


async def _make_league(db_session_factory, league_type=LeagueType.STANDARD, extra_kwargs=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"healthcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Health Test League", commissioner_id=commissioner.id,
                         league_type=league_type, scoring_config={}, roster_slots={}, **(extra_kwargs or {}))
        db.add(league)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"league_id": league.id, "commissioner_id": commissioner.id, "token": token}


async def _add_team(db_session_factory, league_id, owner_id=None, co_owner_id=None, points_for=0.0):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name=f"Team {uuid.uuid4().hex[:6]}", league_id=league_id,
                    owner_id=owner_id, co_owner_id=co_owner_id, roster=[], roster_version=0,
                    points_for=points_for)
        db.add(team)
        await db.commit()
        return team.id


async def _add_weekly_score(db_session_factory, league_id, team_id, week, year=YEAR, score=100.0):
    async with db_session_factory() as db:
        db.add(WeeklyScore(league_id=league_id, team_id=team_id, week=week, year=year, total_score=score))
        await db.commit()


async def _add_lineup(db_session_factory, team_id, week, year=YEAR):
    async with db_session_factory() as db:
        db.add(Lineup(team_id=team_id, week=week, year=year, starters=[]))
        await db.commit()


async def _add_transaction(db_session_factory, league_id, team_id, tx_type=TransactionType.ADD):
    async with db_session_factory() as db:
        db.add(Transaction(league_id=league_id, team_id=team_id, type=tx_type,
                            status=TransactionStatus.APPROVED, details={}))
        await db.commit()


@pytest.mark.asyncio
async def test_no_teams_returns_zeroed_shape(db_session_factory):
    setup = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)
    assert health == {
        "teams": [], "parity_spread": 0.0, "at_risk_count": 0,
        "total_teams": 0, "is_best_ball": False,
    }


@pytest.mark.asyncio
async def test_lineup_rate_computed_correctly_for_non_best_ball(db_session_factory):
    setup = await _make_league(db_session_factory)
    team_id = await _add_team(db_session_factory, setup["league_id"])
    # 4 weeks elapsed, lineup set in 2 of them -> rate 0.5.
    for week in (1, 2, 3, 4):
        await _add_weekly_score(db_session_factory, setup["league_id"], team_id, week)
    for week in (1, 2):
        await _add_lineup(db_session_factory, team_id, week)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)

    team = health["teams"][0]
    assert team["lineup_rate"] == 0.5
    assert health["is_best_ball"] is False


@pytest.mark.asyncio
async def test_lineup_rate_excluded_for_best_ball_regardless_of_lineup_rows(db_session_factory):
    setup = await _make_league(db_session_factory, extra_kwargs={"best_ball_settings": {"enabled": True}})
    team_id = await _add_team(db_session_factory, setup["league_id"])
    await _add_weekly_score(db_session_factory, setup["league_id"], team_id, 1)
    # Even with real Lineup rows present, best-ball must report None, not a number.
    await _add_lineup(db_session_factory, team_id, 1)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)

    team = health["teams"][0]
    assert team["lineup_rate"] is None
    assert team["at_risk"] is False
    assert health["is_best_ball"] is True


@pytest.mark.asyncio
async def test_transaction_count_correct(db_session_factory):
    setup = await _make_league(db_session_factory)
    team_id = await _add_team(db_session_factory, setup["league_id"])
    await _add_weekly_score(db_session_factory, setup["league_id"], team_id, 1)
    for _ in range(3):
        await _add_transaction(db_session_factory, setup["league_id"], team_id)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)

    assert health["teams"][0]["transaction_count"] == 3


@pytest.mark.asyncio
async def test_at_risk_flips_at_the_threshold_boundary(db_session_factory):
    setup = await _make_league(db_session_factory)
    low_team = await _add_team(db_session_factory, setup["league_id"])
    high_team = await _add_team(db_session_factory, setup["league_id"])
    for week in (1, 2, 3, 4):
        await _add_weekly_score(db_session_factory, setup["league_id"], low_team, week)
        await _add_weekly_score(db_session_factory, setup["league_id"], high_team, week)
    # low_team: rate 0.25 (< AT_RISK_LINEUP_RATE), 0 transactions -> at-risk.
    await _add_lineup(db_session_factory, low_team, 1)
    # high_team: rate 1.0, well above threshold -> not at-risk.
    for week in (1, 2, 3, 4):
        await _add_lineup(db_session_factory, high_team, week)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)

    by_id = {t["team_id"]: t for t in health["teams"]}
    assert by_id[low_team]["lineup_rate"] < AT_RISK_LINEUP_RATE
    assert by_id[low_team]["at_risk"] is True
    assert by_id[high_team]["at_risk"] is False
    assert health["at_risk_count"] == 1


@pytest.mark.asyncio
async def test_at_risk_team_with_transactions_is_not_flagged(db_session_factory):
    """Low lineup rate alone isn't enough -- a team that's still trading/
    adding players is clearly not disengaged even if it skips lineups."""
    setup = await _make_league(db_session_factory)
    team_id = await _add_team(db_session_factory, setup["league_id"])
    await _add_weekly_score(db_session_factory, setup["league_id"], team_id, 1)
    await _add_weekly_score(db_session_factory, setup["league_id"], team_id, 2)
    await _add_transaction(db_session_factory, setup["league_id"], team_id)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)

    assert health["teams"][0]["at_risk"] is False


@pytest.mark.asyncio
async def test_co_owned_flag_matches_team_co_owner_id(db_session_factory):
    setup = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        partner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                        username=f"partner{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(partner)
        await db.commit()
        partner_id = partner.id

    solo_id = await _add_team(db_session_factory, setup["league_id"])
    co_owned_id = await _add_team(db_session_factory, setup["league_id"], co_owner_id=partner_id)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)

    by_id = {t["team_id"]: t for t in health["teams"]}
    assert by_id[solo_id]["is_co_owned"] is False
    assert by_id[co_owned_id]["is_co_owned"] is True


@pytest.mark.asyncio
async def test_parity_spread_computed_correctly(db_session_factory):
    setup = await _make_league(db_session_factory)
    low_id = await _add_team(db_session_factory, setup["league_id"], points_for=50.0)
    high_id = await _add_team(db_session_factory, setup["league_id"], points_for=150.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], low_id, 1, score=50.0)
    await _add_weekly_score(db_session_factory, setup["league_id"], high_id, 1, score=150.0)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        health = await compute_league_health(league, db)

    # spread = (max - min) / avg = (150-50)/100 = 1.0
    assert health["parity_spread"] == 1.0


@pytest.mark.asyncio
async def test_health_endpoint_commissioner_only(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"healthoutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/health")
    assert r.status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/health")
    assert r.status_code == 200
    body = r.json()
    assert "teams" in body and "at_risk_count" in body and "parity_spread" in body
