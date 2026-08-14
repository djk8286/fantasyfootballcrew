"""
Tests for Best-Ball's trade-approval management-window gate (Phase 6
Step 6) -- commissioner.review_trade's `if data.action == "approve":`
branch. Trade CREATION (propose) stays always-open regardless (not
exercised here -- these tests insert a PENDING trade directly, same as
test_trade_concurrency.py/test_salary_cap_trades.py already do).

Window settings below are built from the REAL clock (datetime.now),
not mocked -- matching this codebase's established "explicit values
over mocking libraries" convention (see test_best_ball_settings.py's
own real-clock test). _closed_settings/_open_settings are provably
correct for is_window_open regardless of week-boundary wraparound: see
the inline comments for the case analysis.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.services.auth_service import create_access_token


def _closed_settings(now: datetime) -> dict:
    """lock = now (floored to the hour) -- guarantees lock_m <= now_m.
    reopen = now + 3h -- far enough ahead that now_m < reopen_m holds
    even after minute-flooring, in both the wrapping and non-wrapping
    branches of is_window_open. Net result: always closed at `now`."""
    future = now + timedelta(hours=3)
    return {
        "enabled": True,
        "lock_weekday": now.weekday(), "lock_hour": now.hour,
        "reopen_weekday": future.weekday(), "reopen_hour": future.hour,
    }


def _open_settings(now: datetime) -> dict:
    """reopen = now (floored to the hour) -- guarantees reopen_m <= now_m.
    lock = now + 3h -- far enough ahead. Net result: always open at `now`."""
    future = now + timedelta(hours=3)
    return {
        "enabled": True,
        "lock_weekday": future.weekday(), "lock_hour": future.hour,
        "reopen_weekday": now.weekday(), "reopen_hour": now.hour,
    }


async def _make_trade_league(db_session_factory, best_ball_settings=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"bbtcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Best Ball Trade Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={},
                         best_ball_settings=best_ball_settings)
        db.add(league)
        await db.flush()

        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-bbtrade-{i}-{uuid.uuid4().hex[:6]}",
                   first_name=f"Player{i}", last_name="Test", position="RB")
            for i in range(2)
        ]
        db.add_all(players)
        await db.flush()

        team_a = Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id, owner_id=commissioner.id,
                      roster=[players[0].id], roster_version=0)
        team_b = Team(id=str(uuid.uuid4()), name="Team B", league_id=league.id, owner_id=commissioner.id,
                      roster=[players[1].id], roster_version=0)
        db.add_all([team_a, team_b])
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {
            "token": token, "league_id": league.id, "team_a": team_a.id, "team_b": team_b.id,
            "players": [p.id for p in players], "db_session_factory": db_session_factory,
        }


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
async def test_approval_blocked_when_window_closed(client, db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_trade_league(db_session_factory, best_ball_settings=_closed_settings(now))
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 400
    assert "management window is currently closed" in r.json()["detail"]

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
    assert trade.status == TransactionStatus.PENDING


@pytest.mark.asyncio
async def test_approval_succeeds_when_window_open(client, db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_trade_league(db_session_factory, best_ball_settings=_open_settings(now))
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
    assert trade.status == TransactionStatus.APPROVED


@pytest.mark.asyncio
async def test_denial_never_gated_by_window(client, db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_trade_league(db_session_factory, best_ball_settings=_closed_settings(now))
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "deny"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
    assert trade.status == TransactionStatus.DENIED


@pytest.mark.asyncio
async def test_approval_unaffected_when_best_ball_disabled(client, db_session_factory):
    """Regression pin: a league with no best_ball_settings at all (or
    enabled=False) must approve exactly as before this phase."""
    setup = await _make_trade_league(db_session_factory, best_ball_settings=None)
    league_id, team_a, team_b = setup["league_id"], setup["team_a"], setup["team_b"]
    a0, b0 = setup["players"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200
