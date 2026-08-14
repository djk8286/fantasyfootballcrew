"""
Tests for Phase 8 ("AI-Assisted Commissioner Tools") Step 1 -- the
CommissionerDigest data model. Content generation/upsert logic is
covered separately in test_commissioner_digest_service.py once Step 2
lands.
"""
import uuid
import pytest
from sqlalchemy.exc import IntegrityError
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.commissioner_digest import CommissionerDigest


async def _make_league_and_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"digestuser{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(user)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Digest Model Test League", commissioner_id=user.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id, user.id


@pytest.mark.asyncio
async def test_digest_round_trips(db_session_factory):
    league_id, user_id = await _make_league_and_user(db_session_factory)
    async with db_session_factory() as db:
        digest = CommissionerDigest(league_id=league_id, week=1, year=2026,
                                     content="POWER RANKINGS\n1. Team A", generated_by=user_id)
        db.add(digest)
        await db.commit()
        await db.refresh(digest)
        assert digest.id is not None
        assert digest.content.startswith("POWER RANKINGS")
        assert digest.created_at is not None


@pytest.mark.asyncio
async def test_unique_constraint_rejects_duplicate_league_week_year(db_session_factory):
    league_id, user_id = await _make_league_and_user(db_session_factory)
    async with db_session_factory() as db:
        db.add(CommissionerDigest(league_id=league_id, week=1, year=2026, content="first", generated_by=user_id))
        await db.commit()

    with pytest.raises(IntegrityError):
        async with db_session_factory() as db:
            db.add(CommissionerDigest(league_id=league_id, week=1, year=2026, content="second", generated_by=user_id))
            await db.commit()


@pytest.mark.asyncio
async def test_same_league_different_week_is_allowed(db_session_factory):
    league_id, user_id = await _make_league_and_user(db_session_factory)
    async with db_session_factory() as db:
        db.add(CommissionerDigest(league_id=league_id, week=1, year=2026, content="week1", generated_by=user_id))
        db.add(CommissionerDigest(league_id=league_id, week=2, year=2026, content="week2", generated_by=user_id))
        await db.commit()
