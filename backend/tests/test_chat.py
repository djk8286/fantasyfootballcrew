"""
Tests for AI Co-Commissioner Chat (AI Co-Commissioner v1, deferred
item 7) -- chat_service.py's build_chat_context/send_chat_message/
get_chat_history/clear_chat_history, and the GET/POST/DELETE
/leagues/{id}/commissioner/chat endpoints. AIService.chat is
monkeypatched to a spy (same technique every other AI-adjacent
service in this codebase uses) -- no real network call.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.chat_message import ChatMessage
from app.services.auth_service import create_access_token
from app.services.ai_service import AIService
from app.services.chat_service import (
    build_chat_context,
    send_chat_message,
    get_chat_history,
    clear_chat_history,
    MAX_HISTORY_MESSAGES,
    CHAT_RECENT_TRANSACTIONS_LIMIT,
    _compact_health,
    _compact_schedule_insights,
)

YEAR = 2026


async def _make_league(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"chatcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Chat Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Only Team", league_id=league.id,
                    owner_id=commissioner.id, roster=[], roster_version=0)
        db.add(team)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"league_id": league.id, "commissioner_id": commissioner.id, "token": token}


@pytest.mark.asyncio
async def test_build_chat_context_includes_real_data(db_session_factory):
    setup = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        context = await build_chat_context(league, db)

    assert "standings" in context
    assert context["standings"][0]["team_name"] == "Only Team"
    # league_health is compacted for chat -- summary stats + at-risk
    # teams only, not the full per-team breakdown (see _compact_health).
    assert "league_health" in context and "at_risk_teams" in context["league_health"]
    assert "total_teams" in context["league_health"]
    assert "scoring_insights" in context
    assert "schedule_insights" in context
    assert context["recent_transactions"] == []


def test_compact_health_keeps_only_at_risk_teams():
    health = {
        "parity_spread": 1.0, "at_risk_count": 1, "total_teams": 2, "is_best_ball": False,
        "teams": [
            {"team_id": "a", "team_name": "Healthy Team", "at_risk": False, "reason": "fine"},
            {"team_id": "b", "team_name": "Ghost Team", "at_risk": True, "reason": "inactive"},
        ],
    }
    compact = _compact_health(health)
    assert "teams" not in compact  # the full per-team list is dropped
    assert compact["at_risk_teams"] == [{"team_id": "b", "team_name": "Ghost Team", "at_risk": True, "reason": "inactive"}]
    assert compact["total_teams"] == 2


def test_compact_schedule_insights_keeps_only_flagged_teams():
    sos = {
        "available": True, "finale": False, "remaining_weeks": [5, 6, 7],
        "teams": [
            {"team_id": "a", "team_name": "No News", "sos_score": 100.0, "flag": None},
            {"team_id": "b", "team_name": "Hard Stretch", "sos_score": 130.0, "flag": "hard_stretch"},
        ],
    }
    compact = _compact_schedule_insights(sos)
    assert "teams" not in compact
    assert compact["flagged_teams"] == [{"team_id": "b", "team_name": "Hard Stretch", "sos_score": 130.0, "flag": "hard_stretch"}]
    assert compact["remaining_weeks"] == [5, 6, 7]


def test_compact_schedule_insights_passes_through_finale_case_unchanged():
    sos = {"available": True, "finale": True, "summary": "final two", "teams": []}
    assert _compact_schedule_insights(sos) == sos


@pytest.mark.asyncio
async def test_recent_transactions_capped_at_chat_specific_limit(db_session_factory):
    from app.models.transaction import Transaction, TransactionType, TransactionStatus
    setup = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        team_id = (await db.execute(select(Team).where(Team.league_id == setup["league_id"]))).scalar_one().id
    async with db_session_factory() as db:
        for _ in range(CHAT_RECENT_TRANSACTIONS_LIMIT + 5):
            db.add(Transaction(league_id=setup["league_id"], team_id=team_id, type=TransactionType.ADD,
                                status=TransactionStatus.APPROVED, details={}))
        await db.commit()

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        context = await build_chat_context(league, db)

    assert len(context["recent_transactions"]) == CHAT_RECENT_TRANSACTIONS_LIMIT


@pytest.mark.asyncio
async def test_send_chat_message_persists_both_rows_in_order(db_session_factory, monkeypatch):
    async def spy(self, league_name, context, history):
        return "The league looks healthy!"
    monkeypatch.setattr(AIService, "chat", spy)

    setup = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        reply = await send_chat_message(league, "How healthy is the league?", db)

    assert reply.role == "assistant"
    assert reply.content == "The league looks healthy!"

    async with db_session_factory() as db:
        rows = (await db.execute(
            select(ChatMessage).where(ChatMessage.league_id == setup["league_id"]).order_by(ChatMessage.created_at)
        )).scalars().all()
    assert len(rows) == 2
    assert rows[0].role == "user" and rows[0].content == "How healthy is the league?"
    assert rows[1].role == "assistant" and rows[1].content == "The league looks healthy!"


@pytest.mark.asyncio
async def test_no_api_key_reply_still_persists_as_assistant_row(db_session_factory):
    """Regression pin: send_chat_message must never silently drop the
    no-configured-key fallback -- it's a real reply, just not an LLM
    one, and the conversation should show it like any other turn."""
    setup = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        reply = await send_chat_message(league, "hello", db)

    assert reply.role == "assistant"
    assert "not configured" in reply.content

    async with db_session_factory() as db:
        count = len((await db.execute(
            select(ChatMessage).where(ChatMessage.league_id == setup["league_id"])
        )).scalars().all())
    assert count == 2


@pytest.mark.asyncio
async def test_history_capped_and_chronological(db_session_factory, monkeypatch):
    async def spy(self, league_name, context, history):
        return "ok"
    monkeypatch.setattr(AIService, "chat", spy)

    setup = await _make_league(db_session_factory)
    # MAX_HISTORY_MESSAGES + a few extra turns of (user, assistant) pairs.
    turns = MAX_HISTORY_MESSAGES // 2 + 5
    for i in range(turns):
        async with db_session_factory() as db:
            league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
            await send_chat_message(league, f"message {i}", db)

    async with db_session_factory() as db:
        history = await get_chat_history(setup["league_id"], db)

    assert len(history) == MAX_HISTORY_MESSAGES
    # Chronological -- each row's created_at is >= the previous one.
    for i in range(1, len(history)):
        assert history[i].created_at >= history[i - 1].created_at
    # The most recent turns are present (the oldest ones got trimmed).
    contents = [m.content for m in history]
    assert f"message {turns - 1}" in contents
    assert "message 0" not in contents


@pytest.mark.asyncio
async def test_clear_chat_history_removes_only_that_league(db_session_factory, monkeypatch):
    async def spy(self, league_name, context, history):
        return "ok"
    monkeypatch.setattr(AIService, "chat", spy)

    setup_a = await _make_league(db_session_factory)
    setup_b = await _make_league(db_session_factory)

    async with db_session_factory() as db:
        league_a = (await db.execute(select(League).where(League.id == setup_a["league_id"]))).scalar_one()
        await send_chat_message(league_a, "hi from A", db)
    async with db_session_factory() as db:
        league_b = (await db.execute(select(League).where(League.id == setup_b["league_id"]))).scalar_one()
        await send_chat_message(league_b, "hi from B", db)

    async with db_session_factory() as db:
        await clear_chat_history(setup_a["league_id"], db)

    async with db_session_factory() as db:
        remaining_a = await get_chat_history(setup_a["league_id"], db)
        remaining_b = await get_chat_history(setup_b["league_id"], db)
    assert remaining_a == []
    assert len(remaining_b) == 2


@pytest.mark.asyncio
async def test_chat_endpoints_commissioner_only(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"chatoutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    assert (await client.get(f"/leagues/{setup['league_id']}/commissioner/chat")).status_code == 403
    assert (await client.post(f"/leagues/{setup['league_id']}/commissioner/chat", json={"message": "hi"})).status_code == 403
    assert (await client.delete(f"/leagues/{setup['league_id']}/commissioner/chat")).status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/chat")
    assert r.status_code == 200
    assert r.json()["messages"] == []

    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/chat", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json()["role"] == "assistant"

    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/chat")
    assert len(r.json()["messages"]) == 2

    r = await client.delete(f"/leagues/{setup['league_id']}/commissioner/chat")
    assert r.status_code == 200
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/chat")
    assert r.json()["messages"] == []


@pytest.mark.asyncio
async def test_post_chat_empty_message_422s(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/chat", json={"message": "   "})
    assert r.status_code == 422
