"""
Tests for Phase 8 ("AI-Assisted Commissioner Tools") Step 2 --
commissioner_digest_service.py: build_digest_context (context
assembly) and generate_and_save_digest (LLM call + upsert), the latter
with AIService._call_llm monkeypatched to a spy, same technique
test_ai_service.py already uses -- no real network call, no real spend.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.services.commissioner_digest_service import (
    build_digest_context,
    generate_and_save_digest,
    get_digest,
    _get_ai_service,
)
from app.services.ai_service import AIService

WEEK, YEAR = 3, 2026


async def _make_league(db_session_factory, league_type=LeagueType.STANDARD, extra_kwargs=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"digestcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Digest Service Test League", commissioner_id=commissioner.id,
                         league_type=league_type, scoring_config={}, roster_slots={}, **(extra_kwargs or {}))
        db.add(league)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Only Team", league_id=league.id,
                    owner_id=commissioner.id, roster=[], roster_version=0)
        db.add(team)
        await db.commit()
        return league.id, commissioner.id, team.id


@pytest.mark.asyncio
async def test_build_digest_context_omits_combined_standings_for_non_dual_squad(db_session_factory):
    league_id, _commissioner_id, _team_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        context = await build_digest_context(league, WEEK, YEAR, db)
    assert context["combined_standings"] == []
    assert context["features"]["dual_squad"] is False


@pytest.mark.asyncio
async def test_build_digest_context_includes_combined_standings_for_dual_squad(db_session_factory):
    league_id, commissioner_id, _team_id = await _make_league(db_session_factory, league_type=LeagueType.DUAL_SQUAD)
    async with db_session_factory() as db:
        a = Team(id=str(uuid.uuid4()), name="A", league_id=league_id, owner_id=commissioner_id, roster=[], roster_version=0)
        b = Team(id=str(uuid.uuid4()), name="B", league_id=league_id, owner_id=commissioner_id, roster=[], roster_version=0)
        db.add_all([a, b])
        await db.flush()
        a.partner_team_id, b.partner_team_id = b.id, a.id
        await db.commit()

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        context = await build_digest_context(league, WEEK, YEAR, db)
    assert context["features"]["dual_squad"] is True
    assert len(context["combined_standings"]) >= 1


@pytest.mark.asyncio
async def test_build_digest_context_excludes_pending_transactions(db_session_factory):
    league_id, _commissioner_id, team_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        db.add(Transaction(league_id=league_id, team_id=team_id, type=TransactionType.WAIVER,
                            status=TransactionStatus.PENDING, details={"add_player_id": "x"}))
        db.add(Transaction(league_id=league_id, team_id=team_id, type=TransactionType.TRADE,
                            status=TransactionStatus.APPROVED, details={"target_team_id": "y"}))
        await db.commit()

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        context = await build_digest_context(league, WEEK, YEAR, db)

    statuses = [t["status"] for t in context["recent_transactions"]]
    assert "pending" not in statuses
    assert "approved" in statuses


@pytest.mark.asyncio
async def test_build_digest_context_features_match_league_settings(db_session_factory):
    league_id, _commissioner_id, _team_id = await _make_league(
        db_session_factory, extra_kwargs={"salary_cap_settings": {"enabled": True}}
    )
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        context = await build_digest_context(league, WEEK, YEAR, db)
    assert context["features"]["salary_cap"] is True
    assert context["features"]["best_ball"] is False


@pytest.mark.asyncio
async def test_generate_and_save_digest_creates_new_row(db_session_factory, monkeypatch):
    league_id, commissioner_id, _team_id = await _make_league(db_session_factory)

    async def spy(self, prompt):
        return "POWER RANKINGS\n1. Only Team"

    monkeypatch.setattr(AIService, "_call_llm", spy)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        digest = await generate_and_save_digest(league, WEEK, YEAR, commissioner_id, db)

    assert digest.content.startswith("POWER RANKINGS")
    assert digest.generated_by == commissioner_id

    async with db_session_factory() as db:
        fetched = await get_digest(league_id, WEEK, YEAR, db)
        assert fetched is not None
        assert fetched.id == digest.id


@pytest.mark.asyncio
async def test_generate_and_save_digest_regenerate_updates_in_place(db_session_factory, monkeypatch):
    league_id, commissioner_id, _team_id = await _make_league(db_session_factory)

    call_count = {"n": 0}

    async def spy(self, prompt):
        call_count["n"] += 1
        return f"VERSION {call_count['n']}"

    monkeypatch.setattr(AIService, "_call_llm", spy)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        first = await generate_and_save_digest(league, WEEK, YEAR, commissioner_id, db)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        second = await generate_and_save_digest(league, WEEK, YEAR, commissioner_id, db)

    assert first.id == second.id  # same row, not a duplicate
    assert first.content == "VERSION 1"
    assert second.content == "VERSION 2"

    async with db_session_factory() as db:
        from app.models.commissioner_digest import CommissionerDigest
        count = len((await db.execute(
            select(CommissionerDigest).where(CommissionerDigest.league_id == league_id)
        )).scalars().all())
    assert count == 1


@pytest.mark.asyncio
async def test_get_digest_returns_none_when_absent(db_session_factory):
    league_id, _commissioner_id, _team_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        digest = await get_digest(league_id, WEEK, YEAR, db)
    assert digest is None
