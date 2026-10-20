"""
Tests for the Per-Team Player News feature (2026-09-22): a daily AI
news digest scoped to one team's actual roster, mixing real web-search
headlines with this app's own free, structured injury/team-change
detection. _detect_changes/_snapshot are pure functions and covered
directly; generate_and_save_team_news and the /teams/{id}/news
endpoints are exercised for real over the test client -- no API key is
configured in the test environment, so AIService._call_llm returns its
static "not configured" string with zero network calls, same precedent
test_ai_usage_recording.py already established.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueVisibility, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.services.auth_service import create_access_token
from app.services.team_news_service import (
    _detect_changes, _snapshot, get_team_news, generate_and_save_team_news,
)


def _player(pid, injury_status=None, team="KC"):
    return Player(id=pid, sleeper_id=pid, first_name="P", last_name=pid,
                  position="WR", injury_status=injury_status, team=team)


# ─── _detect_changes / _snapshot (pure) ──────────────────────────────────

def test_a_player_never_seen_before_is_reported_as_added():
    changes = _detect_changes([_player("p1")], previous_snapshot={})
    assert changes == [{"player": "P p1", "change": "added to this roster"}]


def test_no_changes_when_snapshot_matches_current_state():
    p = _player("p1", injury_status="Questionable", team="KC")
    snapshot = _snapshot([p])
    assert _detect_changes([p], snapshot) == []


def test_injury_status_change_is_detected():
    p = _player("p1", injury_status="Out", team="KC")
    previous = {"p1": {"injury_status": "Questionable", "team": "KC"}}
    changes = _detect_changes([p], previous)
    assert changes == [{"player": "P p1", "change": "injury status changed from Questionable to Out"}]


def test_team_change_is_detected():
    p = _player("p1", injury_status=None, team="BUF")
    previous = {"p1": {"injury_status": None, "team": "KC"}}
    changes = _detect_changes([p], previous)
    assert changes == [{"player": "P p1", "change": "NFL team changed from KC to BUF"}]


def test_free_agent_team_change_reads_as_free_agent_not_none():
    p = _player("p1", injury_status=None, team=None)
    previous = {"p1": {"injury_status": None, "team": "KC"}}
    changes = _detect_changes([p], previous)
    assert changes == [{"player": "P p1", "change": "NFL team changed from KC to Free Agent"}]


def test_snapshot_captures_injury_status_and_team():
    p = _player("p1", injury_status="Doubtful", team="SF")
    assert _snapshot([p]) == {"p1": {"injury_status": "Doubtful", "team": "SF"}}


# ─── generate_and_save_team_news (service-level) ─────────────────────────

@pytest.mark.asyncio
async def test_generate_and_save_team_news_noops_for_empty_roster(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Empty Roster League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="Empty Team", league_id=league.id,
                     owner_id=commissioner.id, roster=[])
        db.add(team)
        await db.commit()

        result = await generate_and_save_team_news(team, db)
    assert result is None


@pytest.mark.asyncio
async def test_generate_and_save_team_news_creates_then_upserts_on_regenerate(db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="News League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                         first_name="Rost", last_name="Er", position="WR", team="KC")
        db.add(player)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="News Team", league_id=league.id,
                     owner_id=commissioner.id, roster=[player.id])
        db.add(team)
        await db.commit()

        first = await generate_and_save_team_news(team, db)
        assert first is not None
        first_id = first.id
        assert first.player_snapshot == {player.id: {"injury_status": None, "team": "KC"}}

        # Regenerate -- must upsert the SAME row (same id), not create a
        # second one (unique team_id constraint would also catch this,
        # but this pins the actual behavior, not just "doesn't crash").
        second = await generate_and_save_team_news(team, db)
        assert second.id == first_id

        stored = await get_team_news(team.id, db)
        assert stored.id == first_id


# ─── /teams/{id}/news endpoints ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_news_get_is_empty_200_before_anything_generated(client, db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="No News Yet League", commissioner_id=commissioner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="Fresh Team", league_id=league.id,
                     owner_id=commissioner.id, roster=[])
        db.add(team)
        await db.commit()
        team_id = team.id

    r = await client.get(f"/teams/{team_id}/news")  # anonymous
    assert r.status_code == 200
    assert r.json() == {"team_id": team_id, "content": None, "updated_at": None, "articles": []}

    missing = await client.get(f"/teams/{uuid.uuid4()}/news")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_news_generate_then_get_round_trips(client, db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Generate News League", commissioner_id=commissioner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}",
                         first_name="On", last_name="Roster", position="RB", team="SF")
        db.add(player)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Has Roster Team", league_id=league.id,
                     owner_id=commissioner.id, roster=[player.id])
        db.add(team)
        await db.commit()
        team_id = team.id
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})

    client.headers["Authorization"] = f"Bearer {token}"
    gen = await client.post(f"/teams/{team_id}/news/generate")
    assert gen.status_code == 200
    assert "content" in gen.json()

    got = await client.get(f"/teams/{team_id}/news")
    assert got.status_code == 200
    assert got.json()["content"] == gen.json()["content"]


@pytest.mark.asyncio
async def test_news_generate_422s_for_empty_roster(client, db_session_factory):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Empty Roster Endpoint League", commissioner_id=commissioner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={})
        db.add(league)
        team = Team(id=str(uuid.uuid4()), name="No Roster Team", league_id=league.id,
                     owner_id=commissioner.id, roster=[])
        db.add(team)
        await db.commit()
        team_id = team.id
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post(f"/teams/{team_id}/news/generate")
    assert r.status_code == 422
