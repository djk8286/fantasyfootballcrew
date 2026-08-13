"""
Tests for the Guillotine "haunt" twist on waivers (Phase 4 Step 5,
"Guillotine + Custom Twist"): an eliminated team stays in
League.waiver_priority forever (never removed), but process_waivers
must never actually grant it a claim, and submit_claim should reject a
new claim from an eliminated team outright rather than letting it rot
until the next processing run.

Uses the shared 4-team guillotine_seed fixture (conftest.py).
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus


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


async def _add_free_agent(db_session_factory):
    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-{uuid.uuid4().hex[:8]}",
                         first_name="Free", last_name="Agent", position="RB")
        db.add(player)
        await db.commit()
        return player.id


async def _eliminate(db_session_factory, team_id, week=1):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.eliminated_week = week
        await db.commit()


@pytest.mark.asyncio
async def test_process_waivers_denies_a_ghost_teams_claim(client, guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _eliminate(db_session_factory, t2)
    free_agent = await _add_free_agent(db_session_factory)
    await _make_claim(db_session_factory, league_id, t2, free_agent)

    client.headers["Authorization"] = f"Bearer {guillotine_seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()

    assert len(body["granted"]) == 0
    assert len(body["denied"]) == 1
    assert body["denied"][0]["team_id"] == t2
    assert body["denied"][0]["reason"] == "team is eliminated"


@pytest.mark.asyncio
async def test_ghost_teams_priority_position_is_unchanged(client, guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _eliminate(db_session_factory, t2)
    free_agent = await _add_free_agent(db_session_factory)
    await _make_claim(db_session_factory, league_id, t2, free_agent)

    client.headers["Authorization"] = f"Bearer {guillotine_seed['token']}"

    r_before = await client.get(f"/leagues/{league_id}/waivers/priority")
    order_before = [p["id"] for p in r_before.json()["priority"]]

    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    order_after = r.json()["updated_priority"]

    # Only a GRANTED claim ever moves a team in the priority list -- a
    # denied ghost claim must leave the whole order byte-for-byte
    # unchanged (it keeps "haunting" its slot, not losing it).
    assert order_after == order_before
    assert t2 in order_after


@pytest.mark.asyncio
async def test_live_team_behind_ghost_still_processes_normally(client, guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _eliminate(db_session_factory, t1)  # t1 is first in default (creation-order) priority
    ghost_fa = await _add_free_agent(db_session_factory)
    live_fa = await _add_free_agent(db_session_factory)
    await _make_claim(db_session_factory, league_id, t1, ghost_fa)
    await _make_claim(db_session_factory, league_id, t2, live_fa)

    client.headers["Authorization"] = f"Bearer {guillotine_seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()

    granted_team_ids = {g["team_id"] for g in body["granted"]}
    assert t2 in granted_team_ids
    assert t1 not in granted_team_ids

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == t2))
        team2 = result.scalar_one()
    assert live_fa in (team2.roster or [])


@pytest.mark.asyncio
async def test_submit_claim_rejects_an_eliminated_teams_owner(client, guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1 = guillotine_seed["team_ids"][0]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _eliminate(db_session_factory, t1)
    free_agent = await _add_free_agent(db_session_factory)

    client.headers["Authorization"] = f"Bearer {guillotine_seed['token']}"
    r = await client.post(
        f"/leagues/{league_id}/waivers/claims",
        json={"team_id": t1, "add_player_id": free_agent, "drop_player_id": None},
    )
    assert r.status_code == 400
    assert "eliminated" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_free_agents_includes_eliminated_teams_dumped_roster(client, guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t2 = guillotine_seed["team_ids"][1]
    db_session_factory = guillotine_seed["db_session_factory"]

    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-{uuid.uuid4().hex[:8]}",
                         first_name="Dumped", last_name="Rb", position="RB")
        db.add(player)
        await db.commit()
        player_id = player.id

    # Simulate a completed elimination: eliminated + roster already
    # dumped (the CAS write guillotine_service itself performs).
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == t2))
        team = result.scalar_one()
        team.roster = []
        team.eliminated_week = 1
        await db.commit()

    r = await client.get(f"/leagues/{league_id}/waivers/free-agents")
    assert r.status_code == 200
    all_ids = {p["id"] for entries in r.json().values() for p in entries}
    assert player_id in all_ids
