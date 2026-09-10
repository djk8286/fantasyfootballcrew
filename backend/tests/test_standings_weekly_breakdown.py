"""
Tests for the 2026-09-09 enrichment to GET /leagues/{id}/standings/weekly:
each team's lineup_data.breakdown (player_id -> {score, stats, position},
already computed by calculate_week) now also carries each player's real
name, so the frontend can show "who actually contributed what" instead
of just a single team total -- part of the fix for "show the team's
players and their current scores" / "schedule page: show each player's
score AND the team total together."
"""
import pytest
from app.services.standings_service import calculate_week

MATCHUP_WEEK = 3  # see test_matchup_notifications.py's convention


@pytest.mark.asyncio
async def test_weekly_scores_breakdown_includes_player_names(client, seed):
    league_id = seed["league_id"]
    db_session_factory = seed["db_session_factory"]

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.get(f"/leagues/{league_id}/standings/weekly", params={"week": MATCHUP_WEEK, "year": 2026})
    assert r.status_code == 200
    data = r.json()

    team_a_row = next(row for row in data["team_scores"] if row["team_id"] == seed["team_a"])
    breakdown = team_a_row["lineup_data"]["breakdown"]
    # team_a's roster is players[0:2] -- "Player0 Test" and "Player1 Test".
    assert set(breakdown.keys()) == set(seed["players"][0:2])
    for pid in seed["players"][0:2]:
        assert breakdown[pid]["name"].startswith("Player")
        assert breakdown[pid]["name"].endswith("Test")
        assert "score" in breakdown[pid]
        assert "position" in breakdown[pid]


@pytest.mark.asyncio
async def test_weekly_scores_breakdown_unknown_player_falls_back_gracefully(client, seed):
    """A player who's since been deleted from the Player table (rare, but
    lineup_data.breakdown is a frozen historical snapshot keyed by ID)
    shouldn't break the response -- just a clearly-labeled fallback name."""
    league_id = seed["league_id"]
    db_session_factory = seed["db_session_factory"]

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    from sqlalchemy import select, delete
    from app.models.player import Player
    async with db_session_factory() as db:
        await db.execute(delete(Player).where(Player.id == seed["players"][0]))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.get(f"/leagues/{league_id}/standings/weekly", params={"week": MATCHUP_WEEK, "year": 2026})
    assert r.status_code == 200
    data = r.json()
    team_a_row = next(row for row in data["team_scores"] if row["team_id"] == seed["team_a"])
    breakdown = team_a_row["lineup_data"]["breakdown"]
    assert breakdown[seed["players"][0]]["name"] == "Unknown Player"
    assert breakdown[seed["players"][1]]["name"].startswith("Player")
