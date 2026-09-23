"""
Tests for the Player Comparison AI Analysis tool (2026-09-22): season
stats + start/sit verdict between two players under one league's own
scoring. No API key is configured in the test environment, so
AIService._call_llm returns its static "not configured" string with
zero network calls -- same precedent test_ai_usage_recording.py already
established for the other personal AI tools.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueVisibility, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.models.ai_usage_event import AIUsageEvent
from app.models.ai_analysis_history import AIAnalysisHistory
from app.services.auth_service import create_access_token
from app.services.player_comparison_service import build_player_profile
from app.services.scoring_engine import DEFAULT_SCORING


async def _make_user(db_session_factory, username=None):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=username or f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


# ─── player_comparison_service (pure) ────────────────────────────────────

def test_build_player_profile_uses_league_scoring_not_defaults(rb_stats):
    player = Player(id="p1", sleeper_id="p1", first_name="Run", last_name="Ner", position="RB",
                     team="KC", injury_status=None, stats=rb_stats, week_stats={"3": rb_stats})
    # A deliberately different scoring config from DEFAULT_SCORING --
    # asserts this reads the LEAGUE's own rules, not the NFL-wide
    # dashboard's DEFAULT_SCORING (top_performers_service's own concern).
    custom_scoring = {"rushing": {"rush_yd": 1.0, "rush_td": 6}, "receiving": {"rec": 0, "rec_yd": 0, "rec_td": 6}}
    profile = build_player_profile(player, custom_scoring)

    assert profile["name"] == "Run Ner"
    assert profile["position"] == "RB"
    assert profile["team"] == "KC"
    assert profile["injury_status"] == "none reported"
    assert profile["games_played"] == 1
    assert profile["weekly_points"] == {"3": profile["season_points"]}
    # 100 rush_yd * 1.0 + 1 rush_td * 6 = 106
    assert profile["season_points"] == pytest.approx(106.0)


def test_build_player_profile_no_projection_is_none(rb_stats):
    player = Player(id="p2", sleeper_id="p2", first_name="No", last_name="Proj", position="RB",
                     stats={}, week_stats={}, projected_stats=None)
    profile = build_player_profile(player, DEFAULT_SCORING)
    assert profile["projected_points_this_week"] is None
    assert profile["games_played"] == 0


def test_build_player_profile_free_agent_and_injury_defaults():
    player = Player(id="p3", sleeper_id="p3", first_name="Free", last_name="Agent", position="WR",
                     team=None, injury_status=None, stats={}, week_stats={})
    profile = build_player_profile(player, DEFAULT_SCORING)
    assert profile["team"] == "Free Agent"
    assert profile["injury_status"] == "none reported"


# ─── /ai/player-comparison endpoint ───────────────────────────────────────

@pytest.mark.asyncio
async def test_player_comparison_happy_path_records_usage_and_history(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Player Compare League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, league_type=LeagueType.STANDARD,
                         scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="Owner Team", league_id=league.id, owner_id=owner.id, roster=[])
        db.add(team)
        player_a = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                           first_name="Alpha", last_name="Back", position="RB", stats={}, week_stats={})
        player_b = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                           first_name="Bravo", last_name="Wideout", position="WR", stats={}, week_stats={})
        db.add_all([player_a, player_b])
        await db.commit()
        league_id, player_a_id, player_b_id = league.id, player_a.id, player_b.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/player-comparison", json={
        "player_a_id": player_a_id, "player_b_id": player_b_id, "league_id": league_id,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["player_a"]["name"] == "Alpha Back"
    assert body["player_b"]["name"] == "Bravo Wideout"

    async with db_session_factory() as db:
        usage = await db.execute(select(AIUsageEvent).where(AIUsageEvent.endpoint == "player_comparison"))
        assert len(usage.scalars().all()) == 1
        history = await db.execute(
            select(AIAnalysisHistory).where(AIAnalysisHistory.analysis_type == "player_compare")
        )
        rows = history.scalars().all()
        assert len(rows) == 1
        assert rows[0].summary == "Alpha Back vs Bravo Wideout"


@pytest.mark.asyncio
async def test_player_comparison_rejects_same_player_twice(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Solo Player League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                         first_name="Only", last_name="One", position="QB", stats={}, week_stats={})
        db.add(player)
        await db.commit()
        league_id, player_id = league.id, player.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/player-comparison", json={
        "player_a_id": player_id, "player_b_id": player_id, "league_id": league_id,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_player_comparison_404s_on_unknown_player(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Unknown Player League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        real_player = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                              first_name="Real", last_name="Player", position="QB", stats={}, week_stats={})
        db.add(real_player)
        await db.commit()
        league_id, real_player_id = league.id, real_player.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post("/ai/player-comparison", json={
        "player_a_id": real_player_id, "player_b_id": "does-not-exist", "league_id": league_id,
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_player_comparison_rejects_a_non_member_of_the_league(client, db_session_factory):
    owner, _ = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Gated League", commissioner_id=owner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        player_a = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                           first_name="A", last_name="One", position="QB", stats={}, week_stats={})
        player_b = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                           first_name="B", last_name="Two", position="QB", stats={}, week_stats={})
        db.add_all([player_a, player_b])
        await db.commit()
        league_id, player_a_id, player_b_id = league.id, player_a.id, player_b.id

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post("/ai/player-comparison", json={
        "player_a_id": player_a_id, "player_b_id": player_b_id, "league_id": league_id,
    })
    assert r.status_code == 403
