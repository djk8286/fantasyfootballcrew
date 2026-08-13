"""
Tests for waiver-time cap enforcement + the standalone release endpoint
(Phase 5 Step 5, "Salary-Cap + Contract Leagues"). Salary assignment at
draft time is covered separately in test_salary_cap_draft.py.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.contract import Contract, DeadMoney
from app.services.auth_service import create_access_token
from app.services.salary_cap_service import compute_waiver_salary, DEFAULT_SALARY_CAP_SETTINGS


CAP_SETTINGS = {
    "enabled": True, "cap_total": 20.0, "max_roster_size": 3,
    "top_salary": 50.0, "bottom_salary": 1.0, "waiver_salary_pct": 0.6,
    "dead_money_pct": 0.5, "default_contract_years": 2, "waiver_contract_years": 1,
}


async def _make_cap_league(db_session_factory, cap_settings=None, num_teams=2, roster_size=0):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email="wcommish@test.local", username="wcommish", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(
            id=str(uuid.uuid4()), name="Salary Cap Waivers Test League", commissioner_id=commissioner.id,
            league_type=LeagueType.STANDARD, draft_status=DraftStatus.COMPLETED,
            scoring_config={}, roster_slots={}, salary_cap_settings=cap_settings,
        )
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i + 1}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0)
            for i in range(num_teams)
        ]
        db.add_all(teams)
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {
            "token": token, "commissioner_id": commissioner.id, "league_id": league.id,
            "team_ids": [t.id for t in teams], "db_session_factory": db_session_factory,
        }


async def _make_player(db_session_factory, first_name="Free", last_name="Agent", position="RB"):
    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-{uuid.uuid4().hex[:8]}",
                         first_name=first_name, last_name=last_name, position=position)
        db.add(player)
        await db.commit()
        return player.id, player


async def _make_claim(db_session_factory, league_id, team_id, add_id, drop_id=None):
    async with db_session_factory() as db:
        claim = Transaction(
            id=str(uuid.uuid4()), league_id=league_id, team_id=team_id,
            type=TransactionType.WAIVER, status=TransactionStatus.PENDING,
            details={"add_player_id": add_id, "drop_player_id": drop_id},
        )
        db.add(claim)
        await db.commit()
        return claim.id


async def _add_contract(db_session_factory, league_id, team_id, player_id, salary, contract_years, source="draft"):
    async with db_session_factory() as db:
        db.add(Contract(league_id=league_id, team_id=team_id, player_id=player_id,
                         salary=salary, contract_years=contract_years, signed_year=2026,
                         source=source, is_active=True))
        await db.commit()


async def _set_roster(db_session_factory, team_id, player_ids):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.roster = player_ids
        await db.commit()


# ─── process_waivers cap/roster-size enforcement ────────────────────────

@pytest.mark.asyncio
async def test_free_agent_signing_gets_rank_tier_derived_salary(client, db_session_factory):
    setup = await _make_cap_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    league_id, team_id = setup["league_id"], setup["team_ids"][0]
    player_id, player = await _make_player(db_session_factory, "Totally", "Unranked-Nobody")
    await _make_claim(db_session_factory, league_id, team_id, player_id)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()
    assert len(body["granted"]) == 1

    async with db_session_factory() as db:
        result = await db.execute(select(Contract).where(Contract.player_id == player_id, Contract.is_active == True))
        contract = result.scalar_one()

    expected_salary = compute_waiver_salary(player, CAP_SETTINGS)
    assert contract.salary == expected_salary
    assert contract.contract_years == CAP_SETTINGS["waiver_contract_years"]
    assert contract.source == "waiver"


@pytest.mark.asyncio
async def test_claim_exceeding_cap_denied_with_reason(client, db_session_factory):
    settings = dict(CAP_SETTINGS, cap_total=5.0)  # very tight cap
    setup = await _make_cap_league(db_session_factory, cap_settings=settings)
    league_id, team_id = setup["league_id"], setup["team_ids"][0]
    # A ranked star player gets close to top_salary * waiver_salary_pct, well over a $5 cap.
    player_id, _player = await _make_player(db_session_factory, "Christian", "McCaffrey")
    await _make_claim(db_session_factory, league_id, team_id, player_id)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()
    assert len(body["granted"]) == 0
    assert len(body["denied"]) == 1
    assert "exceed salary cap" in body["denied"][0]["reason"]


@pytest.mark.asyncio
async def test_claim_that_fits_after_netting_drop_is_granted(client, db_session_factory):
    settings = dict(CAP_SETTINGS, cap_total=10.0)
    setup = await _make_cap_league(db_session_factory, cap_settings=settings)
    league_id, team_id = setup["league_id"], setup["team_ids"][0]

    drop_id, _drop_player = await _make_player(db_session_factory, "Old", "Bench")
    await _set_roster(db_session_factory, team_id, [drop_id])
    await _add_contract(db_session_factory, league_id, team_id, drop_id, salary=9.0, contract_years=1)

    add_id, _add_player = await _make_player(db_session_factory, "Totally", "Unranked-Two")
    await _make_claim(db_session_factory, league_id, team_id, add_id, drop_id=drop_id)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()
    assert len(body["granted"]) == 1

    async with db_session_factory() as db:
        old_contract = (await db.execute(select(Contract).where(Contract.player_id == drop_id))).scalar_one()
        new_contract = (await db.execute(select(Contract).where(Contract.player_id == add_id, Contract.is_active == True))).scalar_one()
    assert old_contract.is_active is False
    assert new_contract.is_active is True


@pytest.mark.asyncio
async def test_roster_size_exceeding_claim_denied(client, db_session_factory):
    settings = dict(CAP_SETTINGS, max_roster_size=1)
    setup = await _make_cap_league(db_session_factory, cap_settings=settings)
    league_id, team_id = setup["league_id"], setup["team_ids"][0]

    existing_id, _existing = await _make_player(db_session_factory, "Already", "Rostered")
    await _set_roster(db_session_factory, team_id, [existing_id])
    await _add_contract(db_session_factory, league_id, team_id, existing_id, salary=1.0, contract_years=1)

    add_id, _add_player = await _make_player(db_session_factory, "Cant", "AddMe")
    await _make_claim(db_session_factory, league_id, team_id, add_id)  # no drop -- would be 2 players, cap is 1

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()
    assert len(body["granted"]) == 0
    assert body["denied"][0]["reason"] == "would exceed max roster size"


@pytest.mark.asyncio
async def test_non_cap_league_process_waivers_creates_zero_contracts(client, db_session_factory):
    """Regression pin: cap-disabled leagues get byte-for-byte unchanged
    waiver processing."""
    setup = await _make_cap_league(db_session_factory, cap_settings=None)  # disabled (default)
    league_id, team_id = setup["league_id"], setup["team_ids"][0]
    player_id, _player = await _make_player(db_session_factory)
    await _make_claim(db_session_factory, league_id, team_id, player_id)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    assert len(r.json()["granted"]) == 1

    async with db_session_factory() as db:
        contracts = (await db.execute(select(Contract).where(Contract.league_id == league_id))).scalars().all()
    assert contracts == []


# ─── Standalone release endpoint ────────────────────────────────────────

@pytest.mark.asyncio
async def test_standalone_release_deactivates_contract_and_charges_dead_money(client, db_session_factory):
    settings = dict(CAP_SETTINGS)
    setup = await _make_cap_league(db_session_factory, cap_settings=settings)
    league_id, team_id = setup["league_id"], setup["team_ids"][0]

    player_id, _player = await _make_player(db_session_factory)
    await _set_roster(db_session_factory, team_id, [player_id])
    await _add_contract(db_session_factory, league_id, team_id, player_id, salary=10.0, contract_years=2)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/{team_id}/release", json={"player_id": player_id})
    assert r.status_code == 200
    assert player_id not in (r.json()["roster"] or [])

    async with db_session_factory() as db:
        contract = (await db.execute(select(Contract).where(Contract.player_id == player_id))).scalar_one()
        dead_money = (await db.execute(select(DeadMoney).where(DeadMoney.team_id == team_id))).scalars().all()
    assert contract.is_active is False
    assert len(dead_money) == 1
    assert dead_money[0].amount == round(10.0 * settings["dead_money_pct"], 2)


@pytest.mark.asyncio
async def test_standalone_release_charges_zero_dead_money_for_one_year_deal(client, db_session_factory):
    setup = await _make_cap_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    league_id, team_id = setup["league_id"], setup["team_ids"][0]

    player_id, _player = await _make_player(db_session_factory)
    await _set_roster(db_session_factory, team_id, [player_id])
    await _add_contract(db_session_factory, league_id, team_id, player_id, salary=10.0, contract_years=1)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/{team_id}/release", json={"player_id": player_id})
    assert r.status_code == 200

    async with db_session_factory() as db:
        dead_money = (await db.execute(select(DeadMoney).where(DeadMoney.team_id == team_id))).scalars().all()
    assert dead_money == []


@pytest.mark.asyncio
async def test_release_on_non_cap_league_succeeds_with_no_dead_money(client, db_session_factory):
    setup = await _make_cap_league(db_session_factory, cap_settings=None)
    league_id, team_id = setup["league_id"], setup["team_ids"][0]

    player_id, _player = await _make_player(db_session_factory)
    await _set_roster(db_session_factory, team_id, [player_id])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/{team_id}/release", json={"player_id": player_id})
    assert r.status_code == 200
    assert player_id not in (r.json()["roster"] or [])

    async with db_session_factory() as db:
        dead_money = (await db.execute(select(DeadMoney).where(DeadMoney.team_id == team_id))).scalars().all()
    assert dead_money == []


@pytest.mark.asyncio
async def test_release_forbidden_for_non_owner(client, db_session_factory):
    setup = await _make_cap_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    team_id = setup["team_ids"][0]
    player_id, _player = await _make_player(db_session_factory)
    await _set_roster(db_session_factory, team_id, [player_id])

    async with db_session_factory() as db:
        stranger = User(id=str(uuid.uuid4()), email="stranger@test.local", username="strangerw", hashed_password="x")
        db.add(stranger)
        await db.commit()
        stranger_token = create_access_token({"sub": stranger.id, "email": stranger.email})

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post(f"/teams/{team_id}/release", json={"player_id": player_id})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_release_rejects_player_not_on_roster(client, db_session_factory):
    setup = await _make_cap_league(db_session_factory, cap_settings=dict(CAP_SETTINGS))
    team_id = setup["team_ids"][0]
    player_id, _player = await _make_player(db_session_factory)
    # Never added to the roster.

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/{team_id}/release", json={"player_id": player_id})
    assert r.status_code == 400
