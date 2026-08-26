"""
Tests for nfl_schedule_service -- ESPN's public scoreboard is this
app's only source of real NFL game-level data (Sleeper gives per-player
stats only, never a game object). _parse_event is tested against a
real-shaped sample (fetched and inspected directly against the live
endpoint while building this) since it's an unofficial/undocumented API
-- defensive parsing matters here more than for a contracted one.
sync_week_scoreboard's upsert behavior is tested with httpx mocked out,
same technique test_ai_service.py's FakeAsyncClient tests use.
"""
import pytest
from app.services.nfl_schedule_service import _parse_event, sync_week_scoreboard
from app.models.nfl_game import NFLGame
from sqlalchemy import select

REAL_SHAPED_EVENT = {
    "id": "401873286",
    "date": "2026-08-21T00:00Z",
    "status": {"type": {"id": "3", "name": "STATUS_FINAL", "state": "post", "completed": True, "shortDetail": "Final"}},
    "competitions": [{
        "competitors": [
            {"homeAway": "home", "team": {"abbreviation": "HOU", "displayName": "Houston Texans"}, "score": "20"},
            {"homeAway": "away", "team": {"abbreviation": "LV", "displayName": "Las Vegas Raiders"}, "score": "22"},
        ]
    }],
}


def test_parse_event_extracts_expected_shape():
    parsed = _parse_event(REAL_SHAPED_EVENT)
    assert parsed["espn_event_id"] == "401873286"
    assert parsed["home_team"] == "HOU"
    assert parsed["home_score"] == 20
    assert parsed["away_team"] == "LV"
    assert parsed["away_score"] == 22
    assert parsed["completed"] is True
    assert parsed["status_state"] == "post"


def test_parse_event_handles_missing_competitors_defensively():
    """Unofficial API -- an unexpected shape shouldn't raise, just get
    dropped by the caller."""
    assert _parse_event({"id": "1", "competitions": []}) is None
    assert _parse_event({"id": "1", "competitions": [{"competitors": []}]}) is None


def test_parse_event_handles_non_numeric_score_gracefully():
    """A not-yet-started game reports score as "0" or sometimes absent
    entirely -- must not raise either way."""
    event = {
        "id": "2", "date": "2026-08-21T00:00Z",
        "status": {"type": {"state": "pre", "completed": False, "shortDetail": "Sun 1:00 PM"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"abbreviation": "AAA", "displayName": "Team A"}, "score": None},
            {"homeAway": "away", "team": {"abbreviation": "BBB", "displayName": "Team B"}},
        ]}],
    }
    parsed = _parse_event(event)
    assert parsed["home_score"] is None
    assert parsed["away_score"] is None
    assert parsed["completed"] is False


@pytest.mark.asyncio
async def test_sync_week_scoreboard_upserts_by_espn_event_id(db_session_factory, monkeypatch):
    call_count = {"n": 0}

    async def fake_fetch(year, week, season_type):
        call_count["n"] += 1
        # Second call simulates the same game now final, higher score.
        score_away = "22" if call_count["n"] == 1 else "27"
        status = {"state": "in", "completed": False, "shortDetail": "Q3"} if call_count["n"] == 1 else \
                 {"state": "post", "completed": True, "shortDetail": "Final"}
        return {
            "season": {"year": 2026, "type": 2},
            "week": {"number": 1},
            "events": [{
                "id": "401873286", "date": "2026-08-21T00:00Z",
                "status": {"type": status},
                "competitions": [{"competitors": [
                    {"homeAway": "home", "team": {"abbreviation": "HOU", "displayName": "Houston Texans"}, "score": "20"},
                    {"homeAway": "away", "team": {"abbreviation": "LV", "displayName": "Las Vegas Raiders"}, "score": score_away},
                ]}],
            }],
        }

    import app.services.nfl_schedule_service as mod
    monkeypatch.setattr(mod, "fetch_week_scoreboard", fake_fetch)

    async with db_session_factory() as db:
        synced = await sync_week_scoreboard(2026, 1, 2, db)
        assert synced == 1

    async with db_session_factory() as db:
        synced_again = await sync_week_scoreboard(2026, 1, 2, db)
        assert synced_again == 1

    async with db_session_factory() as db:
        result = await db.execute(select(NFLGame).where(NFLGame.espn_event_id == "401873286"))
        rows = result.scalars().all()
        assert len(rows) == 1  # upserted, not duplicated
        assert rows[0].completed is True
        assert rows[0].away_score == 27
