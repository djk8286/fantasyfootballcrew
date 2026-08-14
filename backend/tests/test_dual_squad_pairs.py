"""
Tests for Phase 7 ("Dual-Squad/Mirror") Step 2 -- pair creation
(bulk_add_cpu_teams cross-linking partner_team_id for DUAL_SQUAD
leagues) and claiming (claim_team auto-claiming an unclaimed partner),
plus the defensive max_teams validation on create/update_league.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.services.auth_service import create_access_token


async def _make_league(db_session_factory, league_type=LeagueType.DUAL_SQUAD, max_teams=6):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dspcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Dual Squad Pairs Test League",
                         commissioner_id=commissioner.id, league_type=league_type,
                         scoring_config={}, roster_slots={}, max_teams=max_teams)
        db.add(league)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"token": token, "commissioner_id": commissioner.id, "league_id": league.id,
                "db_session_factory": db_session_factory}


@pytest.mark.asyncio
async def test_bulk_add_cpu_teams_dual_squad_creates_linked_pairs(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/bulk-add/{setup['league_id']}", json={"count": 6, "name_prefix": "CPU Team"})
    assert r.status_code == 201
    body = r.json()
    assert len(body["teams"]) == 6

    async with db_session_factory() as db:
        teams = (await db.execute(select(Team).where(Team.league_id == setup["league_id"]))).scalars().all()
        assert len(teams) == 6
        by_id = {t.id: t for t in teams}
        for t in teams:
            assert t.partner_team_id is not None
            partner = by_id[t.partner_team_id]
            assert partner.partner_team_id == t.id


@pytest.mark.asyncio
async def test_bulk_add_cpu_teams_dual_squad_rounds_down_odd_count(client, db_session_factory):
    setup = await _make_league(db_session_factory, max_teams=6)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/bulk-add/{setup['league_id']}", json={"count": 5, "name_prefix": "CPU Team"})
    assert r.status_code == 201
    # 5 requested -> rounds down to 4, never a half-pair.
    assert len(r.json()["teams"]) == 4


@pytest.mark.asyncio
async def test_bulk_add_cpu_teams_standard_league_unaffected(client, db_session_factory):
    setup = await _make_league(db_session_factory, league_type=LeagueType.STANDARD, max_teams=6)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/bulk-add/{setup['league_id']}", json={"count": 5, "name_prefix": "CPU Team"})
    assert r.status_code == 201
    assert len(r.json()["teams"]) == 5  # no rounding-down for non-dual-squad

    async with db_session_factory() as db:
        teams = (await db.execute(select(Team).where(Team.league_id == setup["league_id"]))).scalars().all()
        assert all(t.partner_team_id is None for t in teams)


@pytest.mark.asyncio
async def test_claim_team_auto_claims_partner(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    league_id = setup["league_id"]
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    await client.post(f"/teams/bulk-add/{league_id}", json={"count": 2, "name_prefix": "CPU Team"})

    async with db_session_factory() as db:
        teams = (await db.execute(select(Team).where(Team.league_id == league_id))).scalars().all()
        first = teams[0]
        partner_id = first.partner_team_id

    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                username=f"dspclaimer{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(user)
        await db.commit()
    token = create_access_token({"sub": user.id, "email": user.email})
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post(f"/teams/{first.id}/claim")
    assert r.status_code == 200
    assert r.json()["owner_id"] == user.id

    async with db_session_factory() as db:
        partner = (await db.execute(select(Team).where(Team.id == partner_id))).scalar_one()
        assert partner.owner_id == user.id
        assert partner.is_cpu is False


@pytest.mark.asyncio
async def test_claim_team_skips_already_claimed_partner(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    league_id = setup["league_id"]
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    await client.post(f"/teams/bulk-add/{league_id}", json={"count": 2, "name_prefix": "CPU Team"})

    async with db_session_factory() as db:
        teams = (await db.execute(select(Team).where(Team.league_id == league_id))).scalars().all()
        first, partner = teams[0], teams[1]

    other_owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                        username=f"dspother{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(other_owner)
        partner_row = (await db.execute(select(Team).where(Team.id == partner.id))).scalar_one()
        partner_row.owner_id = other_owner.id
        partner_row.is_cpu = False
        await db.commit()

    claimer = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"dspclaimer2{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(claimer)
        await db.commit()
    token = create_access_token({"sub": claimer.id, "email": claimer.email})
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post(f"/teams/{first.id}/claim")
    assert r.status_code == 200

    async with db_session_factory() as db:
        partner_row = (await db.execute(select(Team).where(Team.id == partner.id))).scalar_one()
        assert partner_row.owner_id == other_owner.id  # untouched


@pytest.mark.asyncio
async def test_claim_team_non_dual_squad_partner_field_stays_none(client, db_session_factory):
    setup = await _make_league(db_session_factory, league_type=LeagueType.STANDARD)
    league_id = setup["league_id"]
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    await client.post(f"/teams/bulk-add/{league_id}", json={"count": 1, "name_prefix": "CPU Team"})

    async with db_session_factory() as db:
        team = (await db.execute(select(Team).where(Team.league_id == league_id))).scalar_one()

    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                username=f"dspclaimer3{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(user)
        await db.commit()
    token = create_access_token({"sub": user.id, "email": user.email})
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post(f"/teams/{team.id}/claim")
    assert r.status_code == 200
    assert r.json()["partner_team_id"] is None


@pytest.mark.asyncio
async def test_create_league_dual_squad_rejects_odd_max_teams(client, db_session_factory):
    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                username=f"dspcreator{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(user)
        await db.commit()
    token = create_access_token({"sub": user.id, "email": user.email})
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/leagues", json={"name": "Odd", "league_type": "dual_squad", "max_teams": 5})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_league_dual_squad_rejects_max_teams_below_4(client, db_session_factory):
    user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                username=f"dspcreator2{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(user)
        await db.commit()
    token = create_access_token({"sub": user.id, "email": user.email})
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.post("/leagues", json={"name": "TooSmall", "league_type": "dual_squad", "max_teams": 2})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_league_dual_squad_rejects_odd_max_teams(client, db_session_factory):
    setup = await _make_league(db_session_factory, max_teams=6)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.patch(f"/leagues/{setup['league_id']}", json={"max_teams": 7})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_team_clears_partner_link_via_api(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    league_id = setup["league_id"]
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    await client.post(f"/teams/bulk-add/{league_id}", json={"count": 2, "name_prefix": "CPU Team"})

    async with db_session_factory() as db:
        teams = (await db.execute(select(Team).where(Team.league_id == league_id))).scalars().all()
        first, partner = teams[0], teams[1]

    r = await client.delete(f"/teams/{first.id}")
    assert r.status_code == 204

    async with db_session_factory() as db:
        survivor = (await db.execute(select(Team).where(Team.id == partner.id))).scalar_one()
        assert survivor.partner_team_id is None
