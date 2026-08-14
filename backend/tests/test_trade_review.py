"""
Tests for the Smart Trade Review Assistant (AI Co-Commissioner v1) --
trade_review_service.py's context assembly + persistence, and the new
POST /leagues/{id}/commissioner/trades/{id}/analyze endpoint.
AIService._call_llm is monkeypatched throughout, same technique
test_commissioner_digest_service.py already uses -- no real network
call, no real spend.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.services.auth_service import create_access_token
from app.services.ai_service import AIService
from app.services.trade_review_service import build_trade_review_context, generate_and_save_trade_review


async def _make_trade_league(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"tradereviewcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Trade Review Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()

        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-tr-{i}-{uuid.uuid4().hex[:6]}",
                   first_name=f"P{i}", last_name="Test", position="RB")
            for i in range(2)
        ]
        db.add_all(players)
        await db.flush()

        proposer = Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id,
                        owner_id=commissioner.id, roster=[players[0].id], roster_version=0)
        target = Team(id=str(uuid.uuid4()), name="Team B", league_id=league.id,
                      owner_id=commissioner.id, roster=[players[1].id], roster_version=0)
        db.add_all([proposer, target])
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {
            "token": token, "commissioner_id": commissioner.id, "league_id": league.id,
            "proposer_id": proposer.id, "target_id": target.id,
            "players": [p.id for p in players], "db_session_factory": db_session_factory,
        }


async def _make_trade(db_session_factory, league_id, proposer_id, target_id, offered, requested, status=TransactionStatus.PENDING):
    async with db_session_factory() as db:
        trade = Transaction(
            id=str(uuid.uuid4()), league_id=league_id, team_id=proposer_id,
            type=TransactionType.TRADE, status=status,
            details={"target_team_id": target_id, "offered_player_ids": offered, "requested_player_ids": requested},
        )
        db.add(trade)
        await db.commit()
        return trade.id


@pytest.mark.asyncio
async def test_build_trade_review_context_includes_player_names_and_standings(db_session_factory):
    setup = await _make_trade_league(db_session_factory)
    p0, p1 = setup["players"]
    trade_id = await _make_trade(db_session_factory, setup["league_id"], setup["proposer_id"], setup["target_id"], [p0], [p1])

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        proposer = (await db.execute(select(Team).where(Team.id == setup["proposer_id"]))).scalar_one()
        target = (await db.execute(select(Team).where(Team.id == setup["target_id"]))).scalar_one()
        context = await build_trade_review_context(trade, league, proposer, target, db)

    assert context["proposer_name"] == "Team A"
    assert context["target_name"] == "Team B"
    assert any("P0" in name for name in context["offered_players"])
    assert isinstance(context["standings"], list)


@pytest.mark.asyncio
async def test_generate_and_save_trade_review_parses_recommendation(db_session_factory, monkeypatch):
    setup = await _make_trade_league(db_session_factory)
    p0, p1 = setup["players"]
    trade_id = await _make_trade(db_session_factory, setup["league_id"], setup["proposer_id"], setup["target_id"], [p0], [p1])

    async def spy(self, prompt):
        return "RECOMMENDATION: REVIEW CLOSELY\n\nFAIRNESS\nSomewhat lopsided."
    monkeypatch.setattr(AIService, "_call_llm", spy)

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        proposer = (await db.execute(select(Team).where(Team.id == setup["proposer_id"]))).scalar_one()
        target = (await db.execute(select(Team).where(Team.id == setup["target_id"]))).scalar_one()
        review = await generate_and_save_trade_review(trade, league, proposer, target, setup["commissioner_id"], db)

    assert review["recommendation"] == "REVIEW CLOSELY"
    assert "FAIRNESS" in review["content"]


@pytest.mark.asyncio
async def test_malformed_recommendation_never_errors(db_session_factory, monkeypatch):
    setup = await _make_trade_league(db_session_factory)
    p0, p1 = setup["players"]
    trade_id = await _make_trade(db_session_factory, setup["league_id"], setup["proposer_id"], setup["target_id"], [p0], [p1])

    async def spy(self, prompt):
        return "This trade looks fine to me, no strong opinion either way."
    monkeypatch.setattr(AIService, "_call_llm", spy)

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        proposer = (await db.execute(select(Team).where(Team.id == setup["proposer_id"]))).scalar_one()
        target = (await db.execute(select(Team).where(Team.id == setup["target_id"]))).scalar_one()
        review = await generate_and_save_trade_review(trade, league, proposer, target, setup["commissioner_id"], db)

    assert review["recommendation"] is None
    assert review["content"].startswith("This trade")


@pytest.mark.asyncio
async def test_persists_ai_review_without_disturbing_existing_details(db_session_factory, monkeypatch):
    setup = await _make_trade_league(db_session_factory)
    p0, p1 = setup["players"]
    trade_id = await _make_trade(db_session_factory, setup["league_id"], setup["proposer_id"], setup["target_id"], [p0], [p1])

    async def spy(self, prompt):
        return "RECOMMENDATION: APPROVE\n\nLooks good."
    monkeypatch.setattr(AIService, "_call_llm", spy)

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        proposer = (await db.execute(select(Team).where(Team.id == setup["proposer_id"]))).scalar_one()
        target = (await db.execute(select(Team).where(Team.id == setup["target_id"]))).scalar_one()
        await generate_and_save_trade_review(trade, league, proposer, target, setup["commissioner_id"], db)

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
        assert trade.details["offered_player_ids"] == [p0]
        assert trade.details["requested_player_ids"] == [p1]
        assert trade.details["target_team_id"] == setup["target_id"]
        assert trade.details["ai_review"]["recommendation"] == "APPROVE"


@pytest.mark.asyncio
async def test_analyze_endpoint_commissioner_only(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "RECOMMENDATION: APPROVE\n\nok"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_trade_league(db_session_factory)
    p0, p1 = setup["players"]
    trade_id = await _make_trade(db_session_factory, setup["league_id"], setup["proposer_id"], setup["target_id"], [p0], [p1])

    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"troutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/trades/{trade_id}/analyze")
    assert r.status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/trades/{trade_id}/analyze")
    assert r.status_code == 200
    assert r.json()["recommendation"] == "APPROVE"


@pytest.mark.asyncio
async def test_analyze_endpoint_400s_for_non_pending_trade(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "RECOMMENDATION: APPROVE\n\nok"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_trade_league(db_session_factory)
    p0, p1 = setup["players"]
    trade_id = await _make_trade(db_session_factory, setup["league_id"], setup["proposer_id"], setup["target_id"],
                                  [p0], [p1], status=TransactionStatus.APPROVED)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/trades/{trade_id}/analyze")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_review_trade_unaffected_by_prior_analyze(client, db_session_factory, monkeypatch):
    """Regression pin: review_trade's approve/deny flow works identically
    whether or not analyze was called first, and a trade that was
    analyzed then approved shows both details['ai_review'] AND
    status=APPROVED/reviewed_by on the same row."""
    async def spy(self, prompt):
        return "RECOMMENDATION: APPROVE\n\nLooks balanced."
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_trade_league(db_session_factory)
    p0, p1 = setup["players"]
    trade_id = await _make_trade(db_session_factory, setup["league_id"], setup["proposer_id"], setup["target_id"], [p0], [p1])

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/trades/{trade_id}/analyze")
    assert r.status_code == 200

    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        trade = (await db.execute(select(Transaction).where(Transaction.id == trade_id))).scalar_one()
        assert trade.status == TransactionStatus.APPROVED
        assert trade.reviewed_by == setup["commissioner_id"]
        assert trade.details["ai_review"]["recommendation"] == "APPROVE"
