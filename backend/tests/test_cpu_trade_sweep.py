"""QA 2026-10-19 LI9: offers already PENDING when their target is (or later
becomes) CPU-managed must still get a CPU reply -- before, the reply only ran
inside propose_trade, so they sat pending forever."""
import pytest
from sqlalchemy import select

from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from tests.test_draft_queue import _make_league_with_teams, _make_players
from tests.test_qa_round2_league import _rosters


async def _legacy_pending_trade(factory, league, proposer, target, offered, requested) -> str:
    """A trade row exactly as propose_trade wrote it before CPU replies
    existed (or for a then-human target): PENDING, no cpu_response."""
    async with factory() as db:
        t = Transaction(league_id=league.id, team_id=proposer.id, type=TransactionType.TRADE,
                        status=TransactionStatus.PENDING,
                        details={"target_team_id": target.id, "offered_player_ids": [p.id for p in offered],
                                 "requested_player_ids": [p.id for p in requested]})
        db.add(t)
        await db.commit()
        return t.id


async def _trade(factory, trade_id) -> Transaction:
    async with factory() as db:
        return (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()


@pytest.mark.asyncio
async def test_listing_trades_answers_a_stale_pending_cpu_offer(client, db_session_factory):
    league, teams, _c, _token = await _make_league_with_teams(db_session_factory, num_teams=2)
    ps = await _make_players(db_session_factory, n=6)
    await _rosters(db_session_factory, teams, mine=ps[4:6], theirs=ps[0:2])
    tid = await _legacy_pending_trade(db_session_factory, league, teams[0], teams[1], [ps[5]], [ps[0]])

    r = await client.get(f"/leagues/{league.id}/trades")  # public read
    assert r.status_code == 200
    got = next(t for t in r.json() if t["id"] == tid)
    assert got["status"] == "denied"
    assert got["details"]["cpu_response"] == "rejected"
    assert (await _trade(db_session_factory, tid)).status == TransactionStatus.DENIED  # persisted


@pytest.mark.asyncio
async def test_scheduler_sweep_answers_offer_to_team_that_became_cpu(db_session_factory, monkeypatch):
    from app.services import scheduler

    league, teams, _c, _token = await _make_league_with_teams(db_session_factory, num_teams=3)
    ps = await _make_players(db_session_factory, n=6)
    await _rosters(db_session_factory, teams, mine=ps[0:2], theirs=ps[4:6])
    # Target was human when the offer was made...
    async with db_session_factory() as db:
        row = (await db.execute(select(Team).where(Team.id == teams[1].id))).scalar_one()
        row.is_cpu = False
        await db.commit()
    tid = await _legacy_pending_trade(db_session_factory, league, teams[0], teams[1], [ps[0]], [ps[5]])

    monkeypatch.setattr(scheduler, "async_session", db_session_factory)
    assert await scheduler._answer_cpu_trades_once() == 0  # human target: left alone
    assert "cpu_response" not in (await _trade(db_session_factory, tid)).details

    # ...then its owner released it (teams.py flips is_cpu on).
    async with db_session_factory() as db:
        row = (await db.execute(select(Team).where(Team.id == teams[1].id))).scalar_one()
        row.is_cpu = True
        await db.commit()
    assert await scheduler._answer_cpu_trades_once() == 1
    t = await _trade(db_session_factory, tid)
    assert t.details["cpu_response"] == "accepted"
    assert t.status == TransactionStatus.PENDING  # accepted -> commissioner review, as for fresh offers
    assert await scheduler._answer_cpu_trades_once() == 0  # idempotent
