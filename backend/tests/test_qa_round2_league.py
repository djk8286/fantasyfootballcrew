"""QA round 2: CPU trade responses + proposer cancel (#6), inactive-starter
warning (#4), auto-fill skips inactive players (#3), waiver claim names (#5)."""
import pytest
from sqlalchemy import select

from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from tests.test_draft_queue import _make_league_with_teams, _make_players


async def _rosters(factory, teams, mine, theirs):
    async with factory() as db:
        for t, ids in ((teams[0], mine), (teams[1], theirs)):
            row = (await db.execute(select(Team).where(Team.id == t.id))).scalar_one()
            row.roster = [p.id for p in ids]
        await db.commit()


@pytest.mark.asyncio
async def test_cpu_rejects_lopsided_trade_immediately(client, db_session_factory):
    league, teams, _c, token = await _make_league_with_teams(db_session_factory, num_teams=2)
    ps = await _make_players(db_session_factory, n=6)  # search_rank 1..6
    await _rosters(db_session_factory, teams, mine=ps[4:6], theirs=ps[0:2])
    r = await client.post(f"/leagues/{league.id}/trades", headers={"Authorization": f"Bearer {token}"},
                          json={"team_id": teams[0].id, "target_team_id": teams[1].id,
                                "offered_player_ids": [ps[5].id], "requested_player_ids": [ps[0].id]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "denied"
    assert body["details"]["cpu_response"] == "rejected"


@pytest.mark.asyncio
async def test_cpu_accepts_favorable_trade_then_proposer_can_cancel(client, db_session_factory):
    league, teams, _c, token = await _make_league_with_teams(db_session_factory, num_teams=2)
    ps = await _make_players(db_session_factory, n=6)
    await _rosters(db_session_factory, teams, mine=ps[0:2], theirs=ps[4:6])
    h = {"Authorization": f"Bearer {token}"}
    r = await client.post(f"/leagues/{league.id}/trades", headers=h,
                          json={"team_id": teams[0].id, "target_team_id": teams[1].id,
                                "offered_player_ids": [ps[0].id], "requested_player_ids": [ps[5].id]})
    body = r.json()
    assert body["status"] == "pending"  # still goes to commissioner review
    assert body["details"]["cpu_response"] == "accepted"
    r = await client.post(f"/leagues/{league.id}/trades/{body['id']}/cancel", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "denied"
    assert r.json()["details"]["cancelled_by_proposer"] is True
    r = await client.post(f"/leagues/{league.id}/trades/{body['id']}/cancel", headers=h)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_only_proposer_can_cancel(client, db_session_factory):
    from tests.test_draft_queue import _make_user
    league, teams, _c, token = await _make_league_with_teams(db_session_factory, num_teams=2)
    ps = await _make_players(db_session_factory, n=4)
    await _rosters(db_session_factory, teams, mine=ps[0:2], theirs=ps[2:4])
    r = await client.post(f"/leagues/{league.id}/trades", headers={"Authorization": f"Bearer {token}"},
                          json={"team_id": teams[0].id, "target_team_id": teams[1].id,
                                "offered_player_ids": [ps[0].id], "requested_player_ids": [ps[3].id]})
    _u, other = await _make_user(db_session_factory)
    r2 = await client.post(f"/leagues/{league.id}/trades/{r.json()['id']}/cancel",
                           headers={"Authorization": f"Bearer {other}"})
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_starting_out_player_returns_warning_and_autofill_skips_it(client, db_session_factory):
    league, teams, _c, token = await _make_league_with_teams(db_session_factory, num_teams=2)
    ps = await _make_players(db_session_factory, n=3)
    async with db_session_factory() as db:
        out = (await db.execute(select(Player).where(Player.id == ps[0].id))).scalar_one()
        out.injury_status = "Out"
        await db.commit()
    await _rosters(db_session_factory, teams, mine=ps, theirs=[])
    h = {"Authorization": f"Bearer {token}"}
    r = await client.put(f"/teams/{teams[0].id}/lineup?week=1&year=2026", headers=h,
                         json={"starters": [ps[0].id, ps[1].id]})
    assert r.status_code == 200, r.text  # warn, don't block
    assert len(r.json()["warnings"]) == 1 and "Out" in r.json()["warnings"][0]
    r = await client.post(f"/teams/{teams[0].id}/lineup/optimize?week=1&year=2026", headers=h)
    assert r.status_code == 200, r.text
    assert ps[0].id not in r.json()["starters"]
    assert set(r.json()["starters"]) == {ps[1].id, ps[2].id}
    assert r.json()["skipped_inactive"] == [f"{ps[0].first_name} {ps[0].last_name}"]


@pytest.mark.asyncio
async def test_waiver_claims_include_player_names(client, db_session_factory):
    league, teams, _c, token = await _make_league_with_teams(db_session_factory, num_teams=2)
    ps = await _make_players(db_session_factory, n=2)
    async with db_session_factory() as db:
        db.add(Transaction(league_id=league.id, team_id=teams[0].id, type=TransactionType.WAIVER,
                           status=TransactionStatus.PENDING,
                           details={"add_player_id": ps[0].id, "drop_player_id": ps[1].id}))
        await db.commit()
    r = await client.get(f"/leagues/{league.id}/waivers/claims")
    assert r.status_code == 200, r.text
    d = r.json()[0]["details"]
    assert d["add_player_name"] == f"{ps[0].first_name} {ps[0].last_name}"
    assert d["drop_player_name"] == f"{ps[1].first_name} {ps[1].last_name}"
    assert r.json()[0]["status"] == "pending"
