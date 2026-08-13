"""
Tests for trade-time cap enforcement + contract transfer (Phase 5 Step
8, "Salary-Cap + Contract Leagues") -- the highest-risk backend step,
touching the live trade-approval path (commissioner.review_trade).
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.contract import Contract
from app.services.auth_service import create_access_token

CAP_SETTINGS = {
    "enabled": True, "cap_total": 50.0, "max_roster_size": 10,
    "top_salary": 50.0, "bottom_salary": 1.0, "waiver_salary_pct": 0.6,
    "dead_money_pct": 0.5, "default_contract_years": 2, "waiver_contract_years": 1,
}


async def _make_trade_league(db_session_factory, cap_settings=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email="tradecommish@test.local", username="tradecommish", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Salary Cap Trade Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={}, salary_cap_settings=cap_settings)
        db.add(league)
        await db.flush()

        team_a = Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id, owner_id=commissioner.id, roster=[], roster_version=0)
        team_b = Team(id=str(uuid.uuid4()), name="Team B", league_id=league.id, owner_id=commissioner.id, roster=[], roster_version=0)
        db.add_all([team_a, team_b])

        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-trade-{i}", first_name=f"Player{i}", last_name="Test", position="RB")
            for i in range(6)
        ]
        db.add_all(players)
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {
            "token": token, "league_id": league.id, "team_a": team_a.id, "team_b": team_b.id,
            "players": [p.id for p in players], "db_session_factory": db_session_factory,
        }


async def _set_roster(db_session_factory, team_id, player_ids):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.roster = player_ids
        await db.commit()


async def _add_contract(db_session_factory, league_id, team_id, player_id, salary, contract_years=2):
    async with db_session_factory() as db:
        db.add(Contract(league_id=league_id, team_id=team_id, player_id=player_id,
                         salary=salary, contract_years=contract_years, signed_year=2026, source="draft", is_active=True))
        await db.commit()


async def _make_trade(db_session_factory, league_id, proposer_id, target_id, offered, requested):
    async with db_session_factory() as db:
        trade = Transaction(
            id=str(uuid.uuid4()), league_id=league_id, team_id=proposer_id,
            type=TransactionType.TRADE, status=TransactionStatus.PENDING,
            details={"target_team_id": target_id, "offered_player_ids": offered, "requested_player_ids": requested},
        )
        db.add(trade)
        await db.commit()
        return trade.id


@pytest.mark.asyncio
async def test_trade_fitting_both_caps_is_approved_and_contracts_transfer(client, db_session_factory):
    setup = await _make_trade_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"][0], setup["players"][2]

    await _set_roster(db_session_factory, team_a, [a0])
    await _set_roster(db_session_factory, team_b, [b0])
    await _add_contract(db_session_factory, league_id, team_a, a0, salary=10.0)
    await _add_contract(db_session_factory, league_id, team_b, b0, salary=10.0)

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        contract_a0 = (await db.execute(select(Contract).where(Contract.player_id == a0))).scalar_one()
        contract_b0 = (await db.execute(select(Contract).where(Contract.player_id == b0))).scalar_one()

    assert contract_a0.team_id == team_b  # traveled with the trade
    assert contract_b0.team_id == team_a
    assert contract_a0.salary == 10.0  # unchanged
    assert contract_a0.is_active is True


@pytest.mark.asyncio
async def test_trade_blocked_when_proposer_would_exceed_cap(client, db_session_factory):
    setup = await _make_trade_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"][0], setup["players"][2]

    await _set_roster(db_session_factory, team_a, [a0])
    await _set_roster(db_session_factory, team_b, [b0])
    await _add_contract(db_session_factory, league_id, team_a, a0, salary=1.0)
    await _add_contract(db_session_factory, league_id, team_b, b0, salary=60.0)  # clearly over cap_total=50 once proposer gains it

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 400
    assert "exceed the salary cap" in r.json()["detail"]

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
    assert trade.status == TransactionStatus.PENDING  # unchanged, stays pending for retry


@pytest.mark.asyncio
async def test_trade_blocked_when_target_would_exceed_cap(client, db_session_factory):
    setup = await _make_trade_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"][0], setup["players"][2]

    await _set_roster(db_session_factory, team_a, [a0])
    await _set_roster(db_session_factory, team_b, [b0])
    await _add_contract(db_session_factory, league_id, team_a, a0, salary=60.0)  # clearly over cap once target gains it
    await _add_contract(db_session_factory, league_id, team_b, b0, salary=1.0)

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 400
    assert "exceed the salary cap" in r.json()["detail"]


@pytest.mark.asyncio
async def test_trade_leg_with_no_contract_treated_as_zero_grandfather_gap(client, db_session_factory):
    """A player rostered before salary_cap_settings was enabled has no
    Contract row -- must not error, just count as $0 toward cap."""
    setup = await _make_trade_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"][0], setup["players"][2]

    await _set_roster(db_session_factory, team_a, [a0])
    await _set_roster(db_session_factory, team_b, [b0])
    # No Contract rows created for either player at all.

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_trade_exceeding_roster_size_blocked(client, db_session_factory):
    settings = dict(CAP_SETTINGS, max_roster_size=1)
    setup = await _make_trade_league(db_session_factory, cap_settings=settings)
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, a1, b0 = setup["players"][0], setup["players"][1], setup["players"][2]

    await _set_roster(db_session_factory, team_a, [a0, a1])  # already 2, over the 1-player cap in isolation but pre-existing
    await _set_roster(db_session_factory, team_b, [b0])

    # Trade: team_a sends nothing, receives b0 -- team_a would go to 3 players, way over max_roster_size=1.
    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 400
    assert "roster over its size limit" in r.json()["detail"]


@pytest.mark.asyncio
async def test_non_cap_league_trade_approval_unchanged(client, db_session_factory):
    """Regression pin: a non-cap-enabled league's trade approval creates
    zero Contract queries/rows and behaves byte-for-byte as before."""
    setup = await _make_trade_league(db_session_factory, cap_settings=None)
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"][0], setup["players"][2]

    await _set_roster(db_session_factory, team_a, [a0])
    await _set_roster(db_session_factory, team_b, [b0])

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        contracts = (await db.execute(select(Contract).where(Contract.league_id == league_id))).scalars().all()
    assert contracts == []
