"""
Endpoint tests for the Dashboard AI Summaries initiative: the two
NFL-wide panels (dashboard.py -- top-performers, nfl-scores) and the
per-league team-recap pair (GET in leagues.py, open read; POST generate
in commissioner.py, commissioner-gated). AIService._call_llm is
monkeypatched throughout, same technique test_commissioner_digest_endpoints.py
uses -- no real network call.
"""
import uuid
from datetime import datetime, timezone
import pytest
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.weekly_score import WeeklyScore
from app.models.weekly_top_players_summary import WeeklyTopPlayersSummary
from app.models.nfl_game import NFLGame
from app.services.auth_service import create_access_token
from app.services.ai_service import AIService


async def _make_user_and_token(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.com",
                    username=f"dashuser{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email, "token_version": 0})
        return user, token


# ─── Top Performers ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_top_performers_404_when_none_generated_yet(client):
    r = await client.get("/dashboard/top-performers")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_top_performers_returns_most_recent(client, db_session_factory):
    async with db_session_factory() as db:
        db.add(WeeklyTopPlayersSummary(week=1, year=2026, content="old", top_players=[]))
        db.add(WeeklyTopPlayersSummary(week=2, year=2026, content="newest", top_players=[{"name": "X"}]))
        await db.commit()

    r = await client.get("/dashboard/top-performers")
    assert r.status_code == 200
    assert r.json()["content"] == "newest"
    assert r.json()["week"] == 2


@pytest.mark.asyncio
async def test_generate_top_performers_creates_summary(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "Big week for everyone."
    monkeypatch.setattr(AIService, "_call_llm", spy)

    async with db_session_factory() as db:
        db.add(Player(id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), first_name="Star", last_name="Runner",
                       position="RB", team="XXX", week_stats={"1": {"rush_yd": 150}}))
        await db.commit()

    _, token = await _make_user_and_token(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/dashboard/top-performers/generate", params={"week": 1, "year": 2026})
    assert r.status_code == 200
    assert r.json()["content"] == "Big week for everyone."
    assert any(p["name"] == "Star Runner" for p in r.json()["top_players"])


# ─── NFL Scores ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_nfl_scores_404_when_no_games_synced(client):
    r = await client.get("/dashboard/nfl-scores")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_nfl_scores_returns_games_and_null_recap_before_generation(client, db_session_factory):
    async with db_session_factory() as db:
        db.add(NFLGame(
            espn_event_id="1", week=1, year=2026, season_type=2,
            home_team="KC", home_team_name="Kansas City Chiefs", home_score=20,
            away_team="BUF", away_team_name="Buffalo Bills", away_score=17,
            status_state="post", status_detail="Final", completed=True,
            kickoff_at=datetime(2026, 9, 7, 20, 0, tzinfo=timezone.utc),
        ))
        await db.commit()

    r = await client.get("/dashboard/nfl-scores")
    assert r.status_code == 200
    body = r.json()
    assert body["week"] == 1
    assert len(body["games"]) == 1
    assert body["games"][0]["home_team"] == "KC"
    assert body["recap"] is None


# ─── Team Weekly Recap ────────────────────────────────────────────────

async def _make_league_with_scores(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.com",
                             username=f"reccommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Recap EP Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, draft_status=DraftStatus.COMPLETED,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        for i in range(2):
            t = Team(id=str(uuid.uuid4()), name=f"Team {i}", league_id=league.id, owner_id=commissioner.id, roster=[])
            db.add(t)
            await db.flush()
            db.add(WeeklyScore(league_id=league.id, team_id=t.id, week=1, year=2026, total_score=100.0 - i * 10,
                                lineup_data={"breakdown": {}}))
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email, "token_version": 0})
        return {"league_id": league.id, "token": token, "db_session_factory": db_session_factory}


@pytest.mark.asyncio
async def test_get_team_recap_404_when_none_generated(client, db_session_factory):
    setup = await _make_league_with_scores(db_session_factory)
    r = await client.get(f"/leagues/{setup['league_id']}/team-recap", params={"week": 1, "year": 2026})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_generate_and_then_get_team_recap(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "TEAM 0: crushed it."
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league_with_scores(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(
        f"/leagues/{setup['league_id']}/commissioner/team-recap/generate", params={"week": 1, "year": 2026}
    )
    assert r.status_code == 200
    assert r.json()["content"] == "TEAM 0: crushed it."

    # Open GET (no auth header needed) now finds it.
    client.headers.pop("Authorization", None)
    r = await client.get(f"/leagues/{setup['league_id']}/team-recap", params={"week": 1, "year": 2026})
    assert r.status_code == 200
    assert r.json()["content"] == "TEAM 0: crushed it."


@pytest.mark.asyncio
async def test_get_team_recap_with_no_params_returns_most_recent(client, db_session_factory):
    from app.models.team_weekly_recap import TeamWeeklyRecap
    setup = await _make_league_with_scores(db_session_factory)
    async with db_session_factory() as db:
        db.add(TeamWeeklyRecap(league_id=setup["league_id"], week=1, year=2026, content="old"))
        db.add(TeamWeeklyRecap(league_id=setup["league_id"], week=2, year=2026, content="newest"))
        await db.commit()

    r = await client.get(f"/leagues/{setup['league_id']}/team-recap")
    assert r.status_code == 200
    assert r.json()["content"] == "newest"


@pytest.mark.asyncio
async def test_generate_team_recap_requires_commissioner(client, db_session_factory, monkeypatch):
    async def spy(self, prompt):
        return "ok"
    monkeypatch.setattr(AIService, "_call_llm", spy)

    setup = await _make_league_with_scores(db_session_factory)
    _, outsider_token = await _make_user_and_token(db_session_factory)
    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(
        f"/leagues/{setup['league_id']}/commissioner/team-recap/generate", params={"week": 1, "year": 2026}
    )
    assert r.status_code == 403
