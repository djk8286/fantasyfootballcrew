"""
Tests for the notification feature: trade/waiver review creating
notifications for the affected teams, and the notifications API
(list/unread-count/mark-read/mark-all-read). Previously nothing told a
user their trade or waiver was resolved at all -- Transaction.status
just flipped with no caller anywhere downstream of it.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.notification import Notification, NotificationType
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.user import User
from app.models.team import Team
from app.services.auth_service import create_access_token


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


async def _notifications_for(db_session_factory, user_id):
    async with db_session_factory() as db:
        result = await db.execute(select(Notification).where(Notification.user_id == user_id))
        return result.scalars().all()


@pytest.mark.asyncio
async def test_approving_a_trade_notifies_both_teams(client, seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    # seed's commissioner owns both team_a and team_b, so both notify
    # calls land on the same user -- 2 notifications total.
    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    approved = [n for n in notes if n.type == NotificationType.TRADE_APPROVED]
    assert len(approved) == 2
    assert all(not n.is_read for n in approved)
    assert all(n.link == f"/leagues/{league_id}/trades" for n in approved)


@pytest.mark.asyncio
async def test_denying_a_trade_notifies_both_teams(client, seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "deny"})
    assert r.status_code == 200

    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    denied = [n for n in notes if n.type == NotificationType.TRADE_DENIED]
    assert len(denied) == 2


@pytest.mark.asyncio
async def test_trade_notification_goes_to_the_right_specific_owner(client, seed):
    """Distinct owners this time (not both teams owned by the seed
    commissioner) -- confirms notifications land on the actual affected
    users, not just "someone"."""
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    async with db_session_factory() as db:
        owner_a = User(id=str(uuid.uuid4()), email="ownera@test.local", username="ownera", hashed_password="x")
        owner_b = User(id=str(uuid.uuid4()), email="ownerb@test.local", username="ownerb", hashed_password="x")
        db.add_all([owner_a, owner_b])
        await db.flush()
        (await db.execute(select(Team).where(Team.id == team_a))).scalar_one().owner_id = owner_a.id
        (await db.execute(select(Team).where(Team.id == team_b))).scalar_one().owner_id = owner_b.id
        await db.commit()

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    notes_a = await _notifications_for(db_session_factory, owner_a.id)
    notes_b = await _notifications_for(db_session_factory, owner_b.id)
    assert len(notes_a) == 1
    assert len(notes_b) == 1
    assert "Team B" in notes_a[0].message
    assert "Team A" in notes_b[0].message


@pytest.mark.asyncio
async def test_granted_waiver_claim_notifies_the_claiming_team(client, seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    free_agent = str(uuid.uuid4())
    db_session_factory = seed["db_session_factory"]

    await _make_claim(db_session_factory, league_id, team_a, free_agent)

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200

    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    granted_notes = [n for n in notes if n.type == NotificationType.WAIVER_APPROVED]
    assert len(granted_notes) == 1
    assert granted_notes[0].link == f"/leagues/{league_id}/waivers"


@pytest.mark.asyncio
async def test_denied_waiver_claim_notifies_the_claiming_team(client, seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    contested = str(uuid.uuid4())
    db_session_factory = seed["db_session_factory"]

    # team_a wins priority (created first), team_b's identical claim is denied.
    await _make_claim(db_session_factory, league_id, team_a, contested)
    await _make_claim(db_session_factory, league_id, team_b, contested)

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200

    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    denied_notes = [n for n in notes if n.type == NotificationType.WAIVER_DENIED]
    assert len(denied_notes) == 1


@pytest.mark.asyncio
async def test_list_notifications_and_unread_count(client, seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])
    client.headers["Authorization"] = f"Bearer {seed['token']}"
    await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})

    r = await client.get("/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["unread_count"] == 2
    assert len(body["notifications"]) == 2
    assert all(not n["is_read"] for n in body["notifications"])


@pytest.mark.asyncio
async def test_mark_read_and_mark_all_read(client, seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])
    client.headers["Authorization"] = f"Bearer {seed['token']}"
    await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})

    r = await client.get("/notifications")
    notes = r.json()["notifications"]
    assert len(notes) == 2

    r = await client.post(f"/notifications/{notes[0]['id']}/read")
    assert r.status_code == 200

    r = await client.get("/notifications")
    assert r.json()["unread_count"] == 1

    r = await client.post("/notifications/read-all")
    assert r.status_code == 200

    r = await client.get("/notifications")
    assert r.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_cannot_mark_another_users_notification_read(client, seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])
    client.headers["Authorization"] = f"Bearer {seed['token']}"
    await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})

    r = await client.get("/notifications")
    note_id = r.json()["notifications"][0]["id"]

    async with db_session_factory() as db:
        outsider = User(id=str(uuid.uuid4()), email="outsider2@test.local", username="outsider2", hashed_password="x")
        db.add(outsider)
        await db.commit()
        outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/notifications/{note_id}/read")
    assert r.status_code == 404
