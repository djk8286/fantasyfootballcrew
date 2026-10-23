"""Follow-ups to the trade-respond review. One live seat per league on every
claim path, offers only reach people who can answer them, the commissioner
hears about every accepted offer, and eliminated teams can't trade."""
import pytest

from app.models.league import LeagueType, LeagueVisibility
from app.models.notification import NotificationType
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from tests.test_trade_respond import (
    _notes, _propose, _review, _set_league_type, _set_team, _setup, _team,
)
from app.models.league import League
from sqlalchemy import select

TAKEN = "You already manage a team in this league"


async def _open(f, league_id):
    async with f() as db:
        (await db.execute(select(League).where(League.id == league_id))).scalar_one().visibility = LeagueVisibility.OPEN
        await db.commit()


def _claim(client, s, idx, who):
    return client.post(f"/teams/{s['teams'][idx].id}/claim", headers=s["h"][who])


def _assign_owner(client, s, idx, identifier):
    return client.post(f"/teams/{s['teams'][idx].id}/assign-owner", headers=s["h"]["commish"],
                       json={"identifier": identifier})


def _offer(client, s, who, frm, to, offered=(), requested=()):
    return client.post(f"/leagues/{s['league'].id}/trades", headers=s["h"][who],
                       json={"team_id": s["teams"][frm].id, "target_team_id": s["teams"][to].id,
                             "offered_player_ids": list(offered), "requested_player_ids": list(requested)})


@pytest.mark.asyncio
async def test_claiming_a_second_team_is_refused_on_every_claim_path(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    await _open(f, s["league"].id)
    co_id = (await _team(f, s["teams"][1].id)).co_owner_id

    r = await _claim(client, s, 2, "co")  # co-owner of team 1 claims CPU team 2
    assert (r.status_code, r.json()["detail"]) == (409, TAKEN)
    r = await _claim(client, s, 2, "commish")  # commissioner already owns team 0
    assert (r.status_code, r.json()["detail"]) == (409, TAKEN)
    async with f() as db:
        from app.models.user import User
        co_email = (await db.execute(select(User).where(User.id == co_id))).scalar_one().email
    r = await _assign_owner(client, s, 2, co_email)
    assert (r.status_code, r.json()["detail"]) == (409, "That person already manages a team in this league")
    assert (await _team(f, s["teams"][2].id)).is_cpu

    r = await _claim(client, s, 2, "out")  # a newcomer still can
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_dual_squad_partner_and_eliminated_teams_are_exempt(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    await _set_league_type(f, s["league"].id, LeagueType.DUAL_SQUAD)
    await _set_team(f, s["teams"][0].id, partner_team_id=s["teams"][2].id)
    await _set_team(f, s["teams"][2].id, partner_team_id=s["teams"][0].id)
    assert (await _claim(client, s, 2, "commish")).status_code == 200  # own partner squad

    s = await _setup(f)
    await _open(f, s["league"].id)
    await _set_team(f, s["teams"][1].id, eliminated_week=3)
    assert (await _claim(client, s, 2, "owner")).status_code == 200  # Guillotine survivor seat


@pytest.mark.asyncio
async def test_offer_skips_people_on_both_teams(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    owner_id = (await _team(f, s["teams"][1].id)).owner_id
    await _set_team(f, s["teams"][1].id, co_owner_id=s["commish"].id)  # seated before the seat rule

    await _propose(client, s)
    assert await _notes(f, owner_id) == [(NotificationType.TRADE_OFFER, "Team 0 sent you a trade offer.")]
    assert await _notes(f, s["commish"].id) == []


@pytest.mark.asyncio
async def test_commissioner_hears_about_offers_accepted_on_propose(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    review = "Team 2 accepted a trade from Team 1. It needs your review."

    r = await _offer(client, s, "owner", 1, 2, offered=[s["ps"][3].id])  # CPU takes a free player
    assert r.json()["details"]["cpu_response"] == "accepted"
    assert await _notes(f, s["commish"].id) == [(NotificationType.TRADE_ACCEPTED, review)]

    s = await _setup(f)
    await _set_league_type(f, s["league"].id, LeagueType.DUAL_SQUAD)
    owner_id = (await _team(f, s["teams"][1].id)).owner_id
    await _set_team(f, s["teams"][1].id, partner_team_id=s["teams"][2].id)
    await _set_team(f, s["teams"][2].id, is_cpu=False, owner_id=owner_id, partner_team_id=s["teams"][1].id)
    r = await _offer(client, s, "owner", 1, 2, offered=[s["ps"][3].id])
    assert r.json()["details"]["recipient_response"] == "accepted"
    assert await _notes(f, s["commish"].id) == [(NotificationType.TRADE_ACCEPTED, review)]
    assert await _notes(f, owner_id) == []  # nothing to tell the proposer they did themselves


async def _accepted_trade(f, s, frm=0, to=1, offered=(0,), requested=(2,)):
    async with f() as db:
        trade = Transaction(league_id=s["league"].id, team_id=s["teams"][frm].id, type=TransactionType.TRADE,
                            status=TransactionStatus.PENDING,
                            details={"target_team_id": s["teams"][to].id,
                                     "offered_player_ids": [s["ps"][i].id for i in offered],
                                     "requested_player_ids": [s["ps"][i].id for i in requested],
                                     "recipient_response": "accepted"})
        db.add(trade)
        await db.commit()
        return trade.id


@pytest.mark.asyncio
async def test_eliminated_teams_cannot_trade(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    tid = await _accepted_trade(f, s)
    await _set_team(f, s["teams"][1].id, eliminated_week=4)

    for who, frm, to in (("commish", 0, 1), ("owner", 1, 0)):
        r = await _offer(client, s, who, frm, to)
        assert (r.status_code, r.json()["detail"]) == (400, "Team 1 has been eliminated and can no longer trade")

    r = await _review(client, s, tid)
    assert (r.status_code, r.json()["detail"]) == (400, "Team 1 has been eliminated and can no longer trade")
    assert set((await _team(f, s["teams"][0].id)).roster) == {s["ps"][0].id, s["ps"][1].id}
    assert (await _review(client, s, tid, "deny")).status_code == 200  # still clearable


@pytest.mark.asyncio
async def test_commissioner_cannot_approve_their_own_trade(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    await _set_team(f, s["teams"][1].id, co_owner_id=s["commish"].id)  # seated before the seat rule
    tid = await _accepted_trade(f, s)
    r = await _review(client, s, tid)
    assert (r.status_code, r.json()["detail"]) == (400, "You manage both teams in this trade, so you can't approve it")
    assert set((await _team(f, s["teams"][0].id)).roster) == {s["ps"][0].id, s["ps"][1].id}

    s = await _setup(f)
    async with f() as db:
        (await db.execute(select(League).where(League.id == s["league"].id))).scalar_one().co_commissioner_ids = [
            (await _team(f, s["teams"][1].id)).co_owner_id]
        await db.commit()
    tid = await _accepted_trade(f, s, frm=0, to=2, requested=())  # the co-commissioner is on team 1
    r = await _review(client, s, tid)
    assert (r.status_code, r.json()["detail"]) == (
        400, "You manage a team in this trade, so another commissioner has to approve it")
    r = await client.post(f"/leagues/{s['league'].id}/commissioner/trades/{tid}/review",
                          headers=s["h"]["co"], json={"action": "approve"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_sole_commissioner_and_own_dual_squad_pair_can_still_be_approved(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    tid = await _accepted_trade(f, s)  # nobody else could approve it
    assert (await _review(client, s, tid)).status_code == 200

    s = await _setup(f)
    await _set_league_type(f, s["league"].id, LeagueType.DUAL_SQUAD)
    await _set_team(f, s["teams"][0].id, partner_team_id=s["teams"][2].id)
    await _set_team(f, s["teams"][2].id, is_cpu=False, owner_id=s["commish"].id, partner_team_id=s["teams"][0].id)
    tid = await _accepted_trade(f, s, frm=0, to=2, requested=())
    assert (await _review(client, s, tid)).status_code == 200


@pytest.mark.asyncio
async def test_invite_never_seats_someone_on_a_second_team(client, db_session_factory):
    from tests.test_league_invites import _make_raw_invite
    f = db_session_factory
    s = await _setup(f)
    co_id = (await _team(f, s["teams"][1].id)).co_owner_id
    raw = await _make_raw_invite(f, s["league"].id, s["commish"].id)
    r = await client.post(f"/invites/{raw}/accept", headers=s["h"]["co"])
    assert r.status_code == 200
    assert "claimed_team_id" not in r.json()
    assert (await _team(f, s["teams"][2].id)).is_cpu  # the open team stays open

    raw = await _make_raw_invite(f, s["league"].id, s["commish"].id, email="out@test.local")
    r = await client.post(f"/invites/{raw}/accept", headers=s["h"]["out"])
    assert r.json()["claimed_team_id"] == s["teams"][2].id
    assert co_id != (await _team(f, s["teams"][2].id)).owner_id
