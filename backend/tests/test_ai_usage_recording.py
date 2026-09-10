"""
Tests for the 2026-09-09 fix: /ai/lineup, /ai/trade, and /ai/bet
previously made real LLM calls with NO usage record at all -- the
actual reason the admin AI-usage dashboard undercounted real spend
(check_and_record_ai_usage was only ever wired into the AI
Co-Commissioner endpoints, never these three). No API key is
configured in the test environment, so AIService._call_llm returns its
static "not configured" string with zero network calls -- safe to
exercise these endpoints for real over the test client.
"""
import uuid
import pytest
from sqlalchemy import select, func
from app.models.user import User
from app.models.league import League, LeagueVisibility
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.ai_usage_event import AIUsageEvent
from app.services.auth_service import create_access_token


async def _make_user(db_session_factory, username=None):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=username or f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _count_events(db_session_factory, endpoint: str) -> int:
    async with db_session_factory() as db:
        return await db.scalar(select(func.count(AIUsageEvent.id)).where(AIUsageEvent.endpoint == endpoint)) or 0


@pytest.mark.asyncio
async def test_bet_analysis_records_usage_with_user_id_and_no_league(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"

    before = await _count_events(db_session_factory, "bet")
    r = await client.post("/ai/bet", json={"prompt": "Is the over a good bet this week?"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        result = await db.execute(select(AIUsageEvent).where(AIUsageEvent.endpoint == "bet", AIUsageEvent.user_id == user.id))
        rows = result.scalars().all()
    assert len(rows) == before + 1 or len(rows) >= 1
    assert rows[-1].league_id is None
    assert rows[-1].user_id == user.id


@pytest.mark.asyncio
async def test_lineup_analysis_records_usage_with_league_and_user(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="AI Usage Lineup League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="My Team", league_id=league.id, owner_id=owner.id, roster=[])
        db.add(team)
        await db.commit()
        league_id, team_id = league.id, team.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/lineup", json={"team_id": team_id})
    assert r.status_code == 200

    async with db_session_factory() as db:
        result = await db.execute(select(AIUsageEvent).where(AIUsageEvent.endpoint == "lineup", AIUsageEvent.user_id == owner.id))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].league_id == league_id


@pytest.mark.asyncio
async def test_trade_analysis_records_usage_with_league_and_user(client, db_session_factory):
    proposer_owner, token = await _make_user(db_session_factory)
    target_owner, _ = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="AI Usage Trade League", commissioner_id=proposer_owner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        proposer = Team(id=str(uuid.uuid4()), name="Proposer", league_id=league.id, owner_id=proposer_owner.id, roster=[])
        target = Team(id=str(uuid.uuid4()), name="Target", league_id=league.id, owner_id=target_owner.id, roster=[])
        db.add(proposer)
        db.add(target)
        await db.flush()
        trade = Transaction(
            id=str(uuid.uuid4()), league_id=league.id, team_id=proposer.id,
            type=TransactionType.TRADE, status=TransactionStatus.PENDING,
            details={"target_team_id": target.id, "offered_player_ids": [], "requested_player_ids": []},
        )
        db.add(trade)
        await db.commit()
        league_id, trade_id = league.id, trade.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/trade", json={"trade_id": trade_id})
    assert r.status_code == 200

    async with db_session_factory() as db:
        result = await db.execute(select(AIUsageEvent).where(AIUsageEvent.endpoint == "trade", AIUsageEvent.user_id == proposer_owner.id))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].league_id == league_id
