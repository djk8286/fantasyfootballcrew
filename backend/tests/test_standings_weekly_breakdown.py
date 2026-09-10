"""
Tests for the 2026-09-09 enrichment to GET /leagues/{id}/standings/weekly:
each team's lineup_data.breakdown (player_id -> {score, stats, position},
already computed by calculate_week) now also carries each player's real
name, so the frontend can show "who actually contributed what" instead
of just a single team total -- part of the fix for "show the team's
players and their current scores" / "schedule page: show each player's
score AND the team total together."
"""
import uuid
import pytest
from datetime import datetime, timezone
from app.services.standings_service import calculate_week
from app.models.player import Player
from app.models.nfl_game import NFLGame
from app.models.lineup import Lineup

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


# ─── Game status (LIVE/FINAL/not_started) -- 2026-09-10 ────────────────

@pytest.mark.asyncio
async def test_weekly_scores_breakdown_includes_game_status(client, seed):
    """Cross-references each player's NFL team against NFLGame (kept
    fresh for the current week by scheduler._sync_current_week_scoreboard_once)
    to report a real live/final/not_started status, not just a bare score."""
    league_id = seed["league_id"]
    db_session_factory = seed["db_session_factory"]

    async with db_session_factory() as db:
        # team_a's two players: one on a team whose game already
        # finished, one on a team whose game is still being played.
        p_final, p_live = seed["players"][0], seed["players"][1]
        result = await db.execute(
            __import__("sqlalchemy").select(Player).where(Player.id.in_([p_final, p_live]))
        )
        players = {p.id: p for p in result.scalars().all()}
        players[p_final].team = "KC"
        players[p_live].team = "BUF"
        # team_b's players stay team=None -- covers "no team at all"
        # (free agent), which must also read as not_started.

        db.add(NFLGame(
            espn_event_id="evt-final", week=MATCHUP_WEEK, year=2026, season_type=2,
            home_team="KC", home_team_name="Kansas City Chiefs", home_score=24,
            away_team="DEN", away_team_name="Denver Broncos", away_score=17,
            status_state="post", status_detail="Final", completed=True,
            kickoff_at=datetime.now(timezone.utc),
        ))
        db.add(NFLGame(
            espn_event_id="evt-live", week=MATCHUP_WEEK, year=2026, season_type=2,
            home_team="BUF", home_team_name="Buffalo Bills", home_score=10,
            away_team="NYJ", away_team_name="New York Jets", away_score=7,
            status_state="in", status_detail="Q3 4:12", completed=False,
            kickoff_at=datetime.now(timezone.utc),
        ))
        await db.commit()

        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.get(f"/leagues/{league_id}/standings/weekly", params={"week": MATCHUP_WEEK, "year": 2026})
    assert r.status_code == 200
    data = r.json()
    team_a_row = next(row for row in data["team_scores"] if row["team_id"] == seed["team_a"])
    breakdown = team_a_row["lineup_data"]["breakdown"]
    assert breakdown[p_final]["game_status"] == "final"
    assert breakdown[p_live]["game_status"] == "live"

    team_b_row = next(row for row in data["team_scores"] if row["team_id"] == seed["team_b"])
    team_b_breakdown = team_b_row["lineup_data"]["breakdown"]
    for entry in team_b_breakdown.values():
        assert entry["game_status"] == "not_started"  # no NFL team at all


# ─── Bench players -- 2026-09-10 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_weekly_scores_breakdown_includes_bench_players(client, seed):
    """A team with a saved Lineup for the week gets bench entries too now
    (is_bench: true), not just starters -- shown for display, never
    counted toward total_score."""
    league_id = seed["league_id"]
    db_session_factory = seed["db_session_factory"]
    team_a_players = seed["players"][0:2]  # team_a's full 2-player roster

    async with db_session_factory() as db:
        # Only player[0] starts; player[1] sits the bench.
        db.add(Lineup(
            id=str(uuid.uuid4()), team_id=seed["team_a"], week=MATCHUP_WEEK, year=2026,
            starters=[team_a_players[0]],
        ))
        await db.commit()
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.get(f"/leagues/{league_id}/standings/weekly", params={"week": MATCHUP_WEEK, "year": 2026})
    assert r.status_code == 200
    data = r.json()
    team_a_row = next(row for row in data["team_scores"] if row["team_id"] == seed["team_a"])
    breakdown = team_a_row["lineup_data"]["breakdown"]

    assert breakdown[team_a_players[0]]["is_bench"] is False
    assert breakdown[team_a_players[1]]["is_bench"] is True
    # Bench player still gets a real (here, zero -- empty stats) score
    # computed, just excluded from the team total.
    assert "score" in breakdown[team_a_players[1]]
    assert team_a_row["total_score"] == breakdown[team_a_players[0]]["score"]
