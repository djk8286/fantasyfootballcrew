"""A human trade target has to answer the offer before the commissioner can
approve it. Before, nobody on the receiving team could accept or decline, and
the offer just sat at "pending" until the commissioner acted."""
import asyncio

import pytest
from sqlalchemy import select

from app.api.v1 import trades as trades_mod
from app.models.league import League, LeagueType
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


async def _set_team(factory, team_id, **fields):
    async with factory() as db:
        row = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one()
        for k, v in fields.items():
            setattr(row, k, v)
        await db.commit()


async def _set_league_type(factory, league_id, league_type):
    async with factory() as db:
        (await db.execute(select(League).where(League.id == league_id))).scalar_one().league_type = league_type
        await db.commit()


async def _notes(factory, user_id):
    async with factory() as db:
        rows = (await db.execute(select(Notification).where(Notification.user_id == user_id))).scalars().all()
    return sorted((n.type, n.message) for n in rows)


@pytest.mark.asyncio
async def test_cannot_co_own_a_second_team_in_the_same_league(client, db_session_factory):
    """The exploit: own team 2, grab the open co-owner seat on team 1, then
    accept your own lopsided offer on team 1's behalf."""
    f = db_session_factory
    s = await _setup(f)
    await _set_league_type(f, s["league"].id, LeagueType.TWO_MAN)
    attacker, attacker_token = await _make_user(f)
    await _set_team(f, s["teams"][1].id, co_owner_id=None)
    await _set_team(f, s["teams"][2].id, is_cpu=False, owner_id=attacker.id)

    r = await client.post(f"/teams/{s['teams'][1].id}/claim-co-owner",
                          headers={"Authorization": f"Bearer {attacker_token}"})
    assert r.status_code == 409
    assert r.json()["detail"] == "You already manage a team in this league"

    r = await client.post(f"/teams/{s['teams'][1].id}/claim-co-owner", headers=s["h"]["out"])
    assert r.status_code == 200  # a normal 2-Man co-owner still gets in


@pytest.mark.asyncio
async def test_managing_both_teams_does_not_answer_the_offer(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    await _set_team(f, s["teams"][1].id, co_owner_id=s["commish"].id)  # however they got the seat

    trade = await _propose(client, s)
    assert "recipient_response" not in trade["details"]
    r = await _respond(client, s, trade["id"], "commish", "accept")
    assert r.status_code == 403
    assert (await _review(client, s, trade["id"])).status_code == 400
    assert (await _respond(client, s, trade["id"], "owner", "decline")).status_code == 200


@pytest.mark.asyncio
async def test_dual_squad_partner_offer_is_auto_accepted_but_not_other_teams(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    await _set_league_type(f, s["league"].id, LeagueType.DUAL_SQUAD)
    me = s["commish"].id
    await _set_team(f, s["teams"][0].id, partner_team_id=s["teams"][1].id)
    await _set_team(f, s["teams"][1].id, owner_id=me, co_owner_id=None, partner_team_id=s["teams"][0].id)
    await _set_team(f, s["teams"][2].id, is_cpu=False, owner_id=me)

    partner = await _propose(client, s)
    assert partner["details"]["recipient_response"] == "accepted"
    assert (await _review(client, s, partner["id"])).status_code == 200

    r = await client.post(f"/leagues/{s['league'].id}/trades", headers=s["h"]["commish"],
                          json={"team_id": s["teams"][0].id, "target_team_id": s["teams"][2].id,
                                "offered_player_ids": [s["ps"][2].id], "requested_player_ids": []})
    other = r.json()
    assert "recipient_response" not in other["details"]
    assert (await _respond(client, s, other["id"], "commish", "accept")).status_code == 403


@pytest.mark.asyncio
async def test_decline_landing_after_accept_and_approve_is_rejected(client, db_session_factory, monkeypatch):
    """The co-owner's decline reads the offer, stalls, and lands after the
    owner accepted and the commissioner approved. It used to flip the
    trade to DENIED with the players already moved."""
    f = db_session_factory
    s = await _setup(f)
    trade = await _propose(client, s)

    real = trades_mod._get_team_in_league
    stalled, release, calls = asyncio.Event(), asyncio.Event(), {"n": 0}

    async def stall_first_call(team_id, league_id, db):
        calls["n"] += 1
        if calls["n"] == 1:  # the decline, after it read the trade row
            stalled.set()
            await release.wait()
        return await real(team_id, league_id, db)
    monkeypatch.setattr(trades_mod, "_get_team_in_league", stall_first_call)

    decline = asyncio.create_task(_respond(client, s, trade["id"], "co", "decline"))
    await stalled.wait()
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200
    assert (await _review(client, s, trade["id"])).status_code == 200
    release.set()
    assert (await decline).status_code == 409

    async with f() as db:
        row = (await db.execute(select(Transaction).where(Transaction.id == trade["id"]))).scalar_one()
        mine = (await db.execute(select(Team).where(Team.id == s["teams"][0].id))).scalar_one()
    assert row.status == TransactionStatus.APPROVED
    assert row.details["recipient_response"] == "accepted"
    assert s["ps"][2].id in mine.roster


@pytest.mark.asyncio
async def test_commissioner_can_deny_an_unanswered_offer(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _propose(client, s)
    r = await _review(client, s, trade["id"], "deny")
    assert r.status_code == 200
    assert r.json()["status"] == "denied"
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 400


@pytest.mark.asyncio
async def test_offer_and_accept_notify_the_right_people(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    owner_id = (await _team(f, s["teams"][1].id)).owner_id
    co_id = (await _team(f, s["teams"][1].id)).co_owner_id

    trade = await _propose(client, s)
    offer = [(NotificationType.TRADE_OFFER, "Team 0 sent you a trade offer.")]
    assert await _notes(f, owner_id) == offer
    assert await _notes(f, co_id) == offer

    await client.post(f"/leagues/{s['league'].id}/trades", headers=s["h"]["commish"],
                      json={"team_id": s["teams"][0].id, "target_team_id": s["teams"][2].id,
                            "offered_player_ids": [s["ps"][1].id], "requested_player_ids": []})
    assert await _notes(f, s["commish"].id) == []  # CPU answers at once, nobody to ping

    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200
    # The commissioner is also the proposer here. One message, the review one.
    assert await _notes(f, s["commish"].id) == [
        (NotificationType.TRADE_ACCEPTED, "Team 1 accepted a trade from Team 0. It needs your review."),
    ]


async def _team(factory, team_id):
    async with factory() as db:
        return (await db.execute(select(Team).where(Team.id == team_id))).scalar_one()


def test_respond_is_covered_by_the_private_league_walk():
    from tests.test_private_league_reads import _scoped_operations
    ops = {(m, p) for m, p, *_ in _scoped_operations()}
    assert ("POST", "/leagues/{league_id}/trades/{trade_id}/respond") in ops


@pytest.mark.asyncio
async def test_commissioner_cannot_seat_themselves_on_a_second_team(client, db_session_factory):
    """Same exploit through the commissioner tools. PATCH /teams and
    assign-co-owner both used to set any co-owner, including the
    commissioner, who already owns the proposing team."""
    f = db_session_factory
    s = await _setup(f)
    await _set_league_type(f, s["league"].id, LeagueType.TWO_MAN)
    await _set_team(f, s["teams"][1].id, co_owner_id=None)
    team1 = s["teams"][1].id

    r = await client.patch(f"/teams/{team1}", headers=s["h"]["commish"], json={"co_owner_id": s["commish"].id})
    assert r.status_code == 422  # TeamUpdate no longer takes co_owner_id
    r = await client.post(f"/teams/{team1}/assign-co-owner", headers=s["h"]["commish"],
                          json={"identifier": s["commish"].email})
    assert r.status_code == 409
    assert r.json()["detail"] == "That person already manages a team in this league"
    assert (await _team(f, team1)).co_owner_id is None

    # Seated anyway (an older row): the offer is still not theirs to answer.
    await _set_team(f, team1, co_owner_id=s["commish"].id)
    trade = await _propose(client, s)
    assert "recipient_response" not in trade["details"]
    assert (await _respond(client, s, trade["id"], "commish", "accept")).status_code == 403
    assert (await _review(client, s, trade["id"])).status_code == 400
