"""
Tests for the Team Comparison AI Analysis tool (2026-09-22): full-season
trend comparison between two teams in the same league -- weekly scoring
trend, consistency, and position-group strength. No API key is
configured in the test environment, so AIService._call_llm returns its
static "not configured" string with zero network calls -- same "safe to
exercise for real over the test client" precedent test_ai_usage_recording.py
already established for the other personal AI tools.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueVisibility, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.weekly_score import WeeklyScore
from app.models.ai_usage_event import AIUsageEvent
from app.models.ai_analysis_history import AIAnalysisHistory
from app.services.auth_service import create_access_token
from app.services.team_comparison_service import build_team_trend, _trend_label

YEAR = 2026


async def _make_user(db_session_factory, username=None):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=username or f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


# ─── team_comparison_service (pure/service-level) ────────────────────────

def test_trend_label_insufficient_data_below_minimum_weeks():
    assert _trend_label([10.0, 12.0]) == "insufficient data"


def test_trend_label_up_when_recent_half_clearly_higher():
    assert _trend_label([10.0, 10.0, 20.0, 22.0]) == "up"


def test_trend_label_down_when_recent_half_clearly_lower():
    assert _trend_label([22.0, 20.0, 10.0, 10.0]) == "down"


def test_trend_label_steady_when_close():
    assert _trend_label([15.0, 15.5, 15.2, 14.9]) == "steady"


@pytest.mark.asyncio
async def test_build_team_trend_with_no_scored_weeks_yet(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Trend Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="Empty History Team", league_id=league.id,
                     owner_id=commissioner.id, roster=[])
        db.add(team)
        await db.commit()

        trend = await build_team_trend(team, db, {})
    assert trend["games_played"] == 0
    assert trend["average_points"] == 0.0
    assert trend["consistency_stdev"] == 0.0
    assert trend["trend"] == "insufficient data"
    assert trend["position_group_points"] == {}


@pytest.mark.asyncio
async def test_build_team_trend_reflects_real_weekly_scores(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Trend Test League 2", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="Scored Team", league_id=league.id,
                     owner_id=commissioner.id, roster=[])
        db.add(team)
        await db.flush()
        for week, pts in [(1, 90.0), (2, 100.0), (3, 110.0), (4, 130.0)]:
            db.add(WeeklyScore(id=str(uuid.uuid4()), league_id=league.id, team_id=team.id,
                                week=week, year=YEAR, total_score=pts))
        await db.commit()

        trend = await build_team_trend(team, db, {})
    assert trend["games_played"] == 4
    assert trend["weekly_points"] == [
        {"week": 1, "points": 90.0}, {"week": 2, "points": 100.0},
        {"week": 3, "points": 110.0}, {"week": 4, "points": 130.0},
    ]
    assert trend["average_points"] == pytest.approx(107.5)
    assert trend["trend"] == "up"


# ─── /ai/team-comparison endpoint ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_team_comparison_happy_path_records_usage_and_history(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Compare League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, league_type=LeagueType.STANDARD,
                         draft_status=DraftStatus.COMPLETED, scoring_config={}, roster_slots={})
        db.add(league)
        team_a = Team(id=str(uuid.uuid4()), name="Alpha", league_id=league.id, owner_id=owner.id, roster=[])
        team_b = Team(id=str(uuid.uuid4()), name="Bravo", league_id=league.id, owner_id=owner.id, roster=[])
        db.add_all([team_a, team_b])
        await db.commit()
        league_id, team_a_id, team_b_id = league.id, team_a.id, team_b.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/team-comparison", json={"team_a_id": team_a_id, "team_b_id": team_b_id})
    assert r.status_code == 200
    body = r.json()
    assert "analysis" in body
    assert body["team_a_trend"]["team_name"] == "Alpha"
    assert body["team_b_trend"]["team_name"] == "Bravo"

    async with db_session_factory() as db:
        usage = await db.execute(select(AIUsageEvent).where(AIUsageEvent.endpoint == "team_comparison"))
        assert len(usage.scalars().all()) == 1
        history = await db.execute(
            select(AIAnalysisHistory).where(AIAnalysisHistory.analysis_type == "team_compare")
        )
        rows = history.scalars().all()
        assert len(rows) == 1
        assert rows[0].summary == "Alpha vs Bravo"
        assert rows[0].league_id == league_id


@pytest.mark.asyncio
async def test_team_comparison_rejects_same_team_twice(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Same Team League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="Solo", league_id=league.id, owner_id=owner.id, roster=[])
        db.add(team)
        await db.commit()
        team_id = team.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/team-comparison", json={"team_a_id": team_id, "team_b_id": team_id})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_team_comparison_rejects_teams_from_different_leagues(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league1 = League(id=str(uuid.uuid4()), name="League One", commissioner_id=owner.id,
                          visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        league2 = League(id=str(uuid.uuid4()), name="League Two", commissioner_id=owner.id,
                          visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add_all([league1, league2])
        await db.flush()
        team_a = Team(id=str(uuid.uuid4()), name="A", league_id=league1.id, owner_id=owner.id, roster=[])
        team_b = Team(id=str(uuid.uuid4()), name="B", league_id=league2.id, owner_id=owner.id, roster=[])
        db.add_all([team_a, team_b])
        await db.commit()
        team_a_id, team_b_id = team_a.id, team_b.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/team-comparison", json={"team_a_id": team_a_id, "team_b_id": team_b_id})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_team_comparison_rejects_a_non_member_of_the_league(client, db_session_factory):
    owner, _ = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Private-ish League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        team_a = Team(id=str(uuid.uuid4()), name="A", league_id=league.id, owner_id=owner.id, roster=[])
        team_b = Team(id=str(uuid.uuid4()), name="B", league_id=league.id, owner_id=owner.id, roster=[])
        db.add_all([team_a, team_b])
        await db.commit()
        team_a_id, team_b_id = team_a.id, team_b.id

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post("/ai/team-comparison", json={"team_a_id": team_a_id, "team_b_id": team_b_id})
    assert r.status_code == 403
