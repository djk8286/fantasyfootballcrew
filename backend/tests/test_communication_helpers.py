"""
Tests for AI Co-Commissioner v1 Phase 2 Step 5 -- Communication
Helpers: notification_service.notify_league_teams,
message_service.build_message_context/draft_message/send_message, and
the POST /leagues/{id}/commissioner/messages/draft + /send endpoints.
AIService._call_llm is monkeypatched for the draft path only (same
technique test_commissioner_digest_service.py/test_trade_review.py
already use) -- the send path needs no AI mocking at all, since it
never calls the LLM.
"""
import uuid
import pytest
from sqlalchemy import select, func
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.notification import Notification, NotificationType
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.ai_service import AIService
from app.services.notification_service import notify_league_teams
from app.services.message_service import build_message_context, draft_message, send_message

YEAR = 2026


async def _make_league(db_session_factory, extra_kwargs=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"msgcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        kwargs = {"scoring_config": {}, "roster_slots": {}, **(extra_kwargs or {})}
        league = League(id=str(uuid.uuid4()), name="Messages Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, **kwargs)
        db.add(league)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"league_id": league.id, "commissioner_id": commissioner.id, "token": token}


async def _add_team(db_session_factory, league_id, owner_id=None, co_owner_id=None, name=None):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name=name or f"Team {uuid.uuid4().hex[:6]}", league_id=league_id,
                    owner_id=owner_id, co_owner_id=co_owner_id, roster=[], roster_version=0)
        db.add(team)
        await db.commit()
        return team.id


async def _add_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"msguser{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(user)
        await db.commit()
        return user.id


@pytest.mark.asyncio
async def test_notify_league_teams_dedups_shared_owner(db_session_factory):
    setup = await _make_league(db_session_factory)
    shared_user = await _add_user(db_session_factory)
    # Same person owns two different teams in the league.
    await _add_team(db_session_factory, setup["league_id"], owner_id=shared_user)
    await _add_team(db_session_factory, setup["league_id"], owner_id=shared_user)

    async with db_session_factory() as db:
        recipients = await notify_league_teams(db, setup["league_id"], NotificationType.COMMISSIONER_MESSAGE, "hello league")
        await db.commit()

    assert recipients == 1

    async with db_session_factory() as db:
        count = (await db.execute(
            select(func.count(Notification.id)).where(Notification.user_id == shared_user)
        )).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_inactivity_warning_context_includes_real_at_risk_teams(db_session_factory):
    setup = await _make_league(db_session_factory)
    at_risk_team = await _add_team(db_session_factory, setup["league_id"], name="Ghost Team")
    healthy_team = await _add_team(db_session_factory, setup["league_id"], name="Active Team")

    async with db_session_factory() as db:
        # Both teams have scored weeks, but only healthy_team has any
        # engagement signal (a lineup) -- at_risk_team should be flagged.
        for wk in (1, 2, 3, 4):
            db.add(WeeklyScore(league_id=setup["league_id"], team_id=at_risk_team, week=wk, year=YEAR, total_score=10.0))
            db.add(WeeklyScore(league_id=setup["league_id"], team_id=healthy_team, week=wk, year=YEAR, total_score=10.0))
        await db.commit()

    from app.models.lineup import Lineup
    async with db_session_factory() as db:
        for wk in (1, 2, 3, 4):
            db.add(Lineup(team_id=healthy_team, week=wk, year=YEAR, starters=[]))
        await db.commit()

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        context = await build_message_context(league, "inactivity_warning", db)

    assert "Ghost Team" in context["at_risk_teams"]
    assert "Active Team" not in context["at_risk_teams"]


@pytest.mark.asyncio
async def test_playoff_explanation_context_includes_playoff_settings(db_session_factory):
    setup = await _make_league(db_session_factory, extra_kwargs={"playoff_settings": {"enabled": True, "num_teams": 4}})
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        context = await build_message_context(league, "playoff_explanation", db)

    assert context["playoff_settings"]["enabled"] is True
    assert context["playoff_settings"]["num_teams"] == 4


@pytest.mark.asyncio
async def test_draft_message_uses_ai_service_and_never_sends(db_session_factory, monkeypatch):
    captured = {}

    async def spy(self, prompt):
        captured["prompt"] = prompt
        return "Draft content here"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        content = await draft_message(league, "general", "hype", "Reminder about waivers", db)

    assert content == "Draft content here"
    assert "Reminder about waivers" in captured["prompt"]

    async with db_session_factory() as db:
        count = (await db.execute(select(func.count(Notification.id)))).scalar_one()
    assert count == 0  # drafting alone must never notify anyone


@pytest.mark.asyncio
async def test_send_message_creates_one_notification_per_recipient_and_never_calls_llm(db_session_factory, monkeypatch):
    def boom(self, prompt):
        raise AssertionError("send_message must never call the LLM")
    monkeypatch.setattr(AIService, "_call_llm", boom)

    setup = await _make_league(db_session_factory)
    owner_a = await _add_user(db_session_factory)
    owner_b = await _add_user(db_session_factory)
    await _add_team(db_session_factory, setup["league_id"], owner_id=owner_a)
    await _add_team(db_session_factory, setup["league_id"], owner_id=owner_b)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        recipients = await send_message(league, "The deadline is Friday!", db)

    assert recipients == 2

    async with db_session_factory() as db:
        notifications = (await db.execute(
            select(Notification).where(Notification.type == NotificationType.COMMISSIONER_MESSAGE)
        )).scalars().all()
    assert len(notifications) == 2
    assert {n.user_id for n in notifications} == {owner_a, owner_b}
    assert all(n.message == "The deadline is Friday!" for n in notifications)


@pytest.mark.asyncio
async def test_draft_endpoint_commissioner_only(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "ok"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league(db_session_factory)
    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"msgoutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/messages/draft",
                           json={"message_type": "general", "tone": "professional"})
    assert r.status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/messages/draft",
                           json={"message_type": "general", "tone": "professional"})
    assert r.status_code == 200
    assert r.json()["content"] == "ok"


@pytest.mark.asyncio
async def test_draft_endpoint_bad_message_type_422s(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/messages/draft",
                           json={"message_type": "bogus", "tone": "professional"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_send_endpoint_commissioner_only(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    await _add_team(db_session_factory, setup["league_id"], owner_id=await _add_user(db_session_factory))

    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"msgoutsider2{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/messages/send",
                           json={"message_type": "general", "content": "hi"})
    assert r.status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{setup['league_id']}/commissioner/messages/send",
                           json={"message_type": "general", "content": "hi"})
    assert r.status_code == 200
    assert r.json()["recipients"] == 1
