"""QA regression part 2 (2026-10-19): Process Waivers resolves every
pending claim in one run (BUG H); a 401'd trade proposal never creates a
trade, so the client's refresh-and-retry can't double-create (BUG J)."""
import uuid

import pytest
from sqlalchemy import select, func

from app.models.league import League
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from tests.test_waiver_concurrency import _make_claim


@pytest.mark.asyncio
async def test_one_process_run_handles_every_claim_in_rolling_priority(client, seed):
    f = seed["db_session_factory"]
    league_id, a, b = seed["league_id"], seed["team_a"], seed["team_b"]
    async with f() as db:
        lg = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        lg.waiver_priority = [a, b, seed["team_c"]]
        await db.commit()
    x, y, z = (str(uuid.uuid4()) for _ in range(3))
    a_x = await _make_claim(f, league_id, a, x)
    a_y = await _make_claim(f, league_id, a, y)
    b_x = await _make_claim(f, league_id, b, x)  # loses X to A (higher priority)
    b_z = await _make_claim(f, league_id, b, z)

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {(g["team_id"], g["add_player_id"]) for g in body["granted"]} == {(a, x), (a, y), (b, z)}
    assert [(d["team_id"], d["add_player_id"]) for d in body["denied"]] == [(b, x)]
    assert body["skipped"] == []

    async with f() as db:
        statuses = {t.id: t.status for t in (await db.execute(
            select(Transaction).where(Transaction.id.in_([a_x, a_y, b_x, b_z])))).scalars()}
        team_a = (await db.execute(select(Team).where(Team.id == a))).scalar_one()
        team_b = (await db.execute(select(Team).where(Team.id == b))).scalar_one()
    assert statuses == {a_x: TransactionStatus.APPROVED, a_y: TransactionStatus.APPROVED,
                        b_x: TransactionStatus.DENIED, b_z: TransactionStatus.APPROVED}
    assert {x, y} <= set(team_a.roster) and z in team_b.roster and x not in team_b.roster
    # Nothing left for a second click.
    again = (await client.post(f"/leagues/{league_id}/waivers/process")).json()
    assert again["granted"] == [] and again["denied"] == []


@pytest.mark.asyncio
async def test_unauthenticated_trade_proposal_creates_nothing_and_retry_creates_one(client, seed):
    f = seed["db_session_factory"]
    league_id, a, b = seed["league_id"], seed["team_a"], seed["team_b"]
    a0, _a1, b0, _b1 = seed["players"][:4]
    payload = {"team_id": a, "target_team_id": b, "offered_player_ids": [a0], "requested_player_ids": [b0]}

    async def count():
        async with f() as db:
            return await db.scalar(select(func.count(Transaction.id)).where(
                Transaction.league_id == league_id, Transaction.type == TransactionType.TRADE))

    # Expired/missing access token -> 401 from the auth dependency, before
    # the handler runs: nothing written.
    r = await client.post(f"/leagues/{league_id}/trades", json=payload, headers={"Authorization": "Bearer expired.garbage"})
    assert r.status_code == 401
    assert await count() == 0
    # The client's single retry after refreshing creates exactly one trade.
    r = await client.post(f"/leagues/{league_id}/trades", json=payload, headers={"Authorization": f"Bearer {seed['token']}"})
    assert r.status_code == 201, r.text
    assert await count() == 1


@pytest.mark.asyncio
async def test_players_batched_lookup_by_ids(client, seed):
    ids = seed["players"][:3]
    r = await client.get("/players", params={"ids": ",".join(ids + [ids[0], "nope"])})
    assert r.status_code == 200
    assert sorted(p["id"] for p in r.json()) == sorted(ids)
    assert (await client.get("/players", params={"ids": ""})).json() == []
    too_many = ",".join(str(uuid.uuid4()) for _ in range(401))
    assert (await client.get("/players", params={"ids": too_many})).status_code == 422
