"""A human trade target has to answer the offer before the commissioner can
approve it. Before, nobody on the receiving team could accept or decline, and
the offer just sat at "pending" until the commissioner acted."""
import pytest
from sqlalchemy import select

from app.models.notification import Notification, NotificationType
from app.models.team import Team
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from tests.test_draft_queue import _make_league_with_teams, _make_players, _make_user
from tests.test_qa_round2_league import _rosters


async def _setup(factory):
    league, teams, commish, commish_token = await _make_league_with_teams(factory, num_teams=3)
    owner, owner_token = await _make_user(factory)
    co_owner, co_token = await _make_user(factory)
    outsider, out_token = await _make_user(factory)
    ps = await _make_players(factory, n=4)
    await _rosters(factory, teams, mine=ps[0:2], theirs=ps[2:4])
    async with factory() as db:
        row = (await db.execute(select(Team).where(Team.id == teams[1].id))).scalar_one()
        row.is_cpu, row.owner_id, row.co_owner_id = False, owner.id, co_owner.id
        await db.commit()
    return {"league": league, "teams": teams, "ps": ps, "commish": commish,
            "h": {k: {"Authorization": f"Bearer {t}"} for k, t in
                  (("commish", commish_token), ("owner", owner_token), ("co", co_token), ("out", out_token))}}


async def _propose(client, s):
    r = await client.post(f"/leagues/{s['league'].id}/trades", headers=s["h"]["commish"],
                          json={"team_id": s["teams"][0].id, "target_team_id": s["teams"][1].id,
                                "offered_player_ids": [s["ps"][0].id], "requested_player_ids": [s["ps"][2].id]})
    assert r.status_code == 201
    return r.json()


def _respond(client, s, trade_id, who, action):
    return client.post(f"/leagues/{s['league'].id}/trades/{trade_id}/respond", headers=s["h"][who], json={"action": action})


def _review(client, s, trade_id, action="approve"):
    return client.post(f"/leagues/{s['league'].id}/commissioner/trades/{trade_id}/review",
                       headers=s["h"]["commish"], json={"action": action})


@pytest.mark.asyncio
async def test_owner_accepts_then_commissioner_approves(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _propose(client, s)
    assert trade["status"] == "pending"
    assert "recipient_response" not in trade["details"]

    r = await _review(client, s, trade["id"])
    assert r.status_code == 400
    assert "hasn't accepted" in r.json()["detail"]

    r = await _respond(client, s, trade["id"], "owner", "accept")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["details"]["recipient_response"] == "accepted"

    assert (await _review(client, s, trade["id"])).status_code == 200
    async with db_session_factory() as db:
        mine = (await db.execute(select(Team).where(Team.id == s["teams"][0].id))).scalar_one()
        theirs = (await db.execute(select(Team).where(Team.id == s["teams"][1].id))).scalar_one()
    assert set(mine.roster) == {s["ps"][1].id, s["ps"][2].id}
    assert set(theirs.roster) == {s["ps"][0].id, s["ps"][3].id}


@pytest.mark.asyncio
async def test_co_owner_declines_and_proposer_hears_about_it(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _propose(client, s)

    r = await _respond(client, s, trade["id"], "co", "decline")
    assert r.status_code == 200
    assert r.json()["status"] == "denied"
    assert r.json()["details"]["recipient_response"] == "declined"

    async with db_session_factory() as db:
        notes = (await db.execute(select(Notification).where(Notification.user_id == s["commish"].id))).scalars().all()
    assert [(n.type, n.message) for n in notes] == [(NotificationType.TRADE_DENIED, "Team 1 declined your trade offer.")]
    assert (await _review(client, s, trade["id"])).status_code == 400  # closed


@pytest.mark.asyncio
async def test_only_the_receiving_team_can_answer(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _propose(client, s)
    assert (await _respond(client, s, trade["id"], "out", "accept")).status_code == 403
    assert (await _respond(client, s, trade["id"], "commish", "accept")).status_code == 403  # proposer
    assert (await _respond(client, s, trade["id"], "owner", "maybe")).status_code == 422


@pytest.mark.asyncio
async def test_cannot_answer_twice_or_after_cancel(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _propose(client, s)
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200
    r = await _respond(client, s, trade["id"], "co", "decline")
    assert r.status_code == 400

    other = await _propose(client, s)
    await client.post(f"/leagues/{s['league'].id}/trades/{other['id']}/cancel", headers=s["h"]["commish"])
    assert (await _respond(client, s, other["id"], "owner", "accept")).status_code == 400


@pytest.mark.asyncio
async def test_offer_made_before_this_fix_can_still_be_answered(client, db_session_factory):
    s = await _setup(db_session_factory)
    async with db_session_factory() as db:
        legacy = Transaction(league_id=s["league"].id, team_id=s["teams"][0].id, type=TransactionType.TRADE,
                             status=TransactionStatus.PENDING,
                             details={"target_team_id": s["teams"][1].id, "offered_player_ids": [s["ps"][0].id],
                                      "requested_player_ids": [s["ps"][2].id]})
        db.add(legacy)
        await db.commit()
        tid = legacy.id
    assert (await _respond(client, s, tid, "owner", "accept")).status_code == 200
    assert (await _review(client, s, tid)).status_code == 200


@pytest.mark.asyncio
async def test_cpu_offers_are_answered_by_the_cpu_not_respond(client, db_session_factory):
    s = await _setup(db_session_factory)
    r = await client.post(f"/leagues/{s['league'].id}/trades", headers=s["h"]["commish"],
                          json={"team_id": s["teams"][0].id, "target_team_id": s["teams"][2].id,
                                "offered_player_ids": [s["ps"][0].id], "requested_player_ids": []})
    trade = r.json()
    assert trade["details"]["cpu_response"] == "accepted"
    assert (await _respond(client, s, trade["id"], "owner", "decline")).status_code == 403
    assert (await _review(client, s, trade["id"])).status_code == 200
