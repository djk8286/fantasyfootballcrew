"""
Tests for Best-Ball's lineup-endpoint changes (Phase 6 Step 9) --
GET /teams/{id}/lineup reads starters from WeeklyScore.lineup_data
(auto_starters) instead of any Lineup row for a best-ball league, and
PUT/POST (manual set / optimize) are both blocked with a 400. No prior
test coverage existed for lineups.py at all before this file.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.models.lineup import Lineup
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token

WEEK, YEAR = 1, 2026


async def _make_league_and_team(db_session_factory, best_ball_enabled=True):
    async with db_session_factory() as db:
        owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"bblowner{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(owner)
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Best Ball Lineup Test League", commissioner_id=owner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={},
                         best_ball_settings={"enabled": best_ball_enabled})
        db.add(league)
        await db.flush()

        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-bbl-{i}-{uuid.uuid4().hex[:6]}",
                   first_name=f"P{i}", last_name="Test", position="RB")
            for i in range(3)
        ]
        db.add_all(players)
        await db.flush()
        player_ids = [p.id for p in players]

        team = Team(id=str(uuid.uuid4()), name="Only Team", league_id=league.id,
                    owner_id=owner.id, roster=player_ids, roster_version=0)
        db.add(team)
        await db.commit()

        token = create_access_token({"sub": owner.id, "email": owner.email})
        return {"token": token, "league_id": league.id, "team_id": team.id,
                "players": player_ids, "db_session_factory": db_session_factory}


@pytest.mark.asyncio
async def test_get_lineup_best_ball_uses_weekly_score_auto_starters(client, db_session_factory):
    setup = await _make_league_and_team(db_session_factory, best_ball_enabled=True)
    p0, p1, p2 = setup["players"]

    async with db_session_factory() as db:
        db.add(WeeklyScore(league_id=setup["league_id"], team_id=setup["team_id"], week=WEEK, year=YEAR,
                            total_score=10.0, lineup_data={"auto_lineup": True, "auto_starters": [p0, p1]}))
        await db.commit()

    r = await client.get(f"/teams/{setup['team_id']}/lineup", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
    body = r.json()
    assert body["best_ball"] is True
    assert set(body["starters"]) == {p0, p1}
    assert body["has_lineup_set"] is True
    by_id = {p["id"]: p for p in body["roster"]}
    assert by_id[p0]["is_starter"] is True
    assert by_id[p2]["is_starter"] is False


@pytest.mark.asyncio
async def test_get_lineup_best_ball_ignores_existing_lineup_row(client, db_session_factory):
    """A saved Lineup row (e.g. left over from before best-ball was
    enabled) must be completely ignored once best_ball is on."""
    setup = await _make_league_and_team(db_session_factory, best_ball_enabled=True)
    p0, p1, p2 = setup["players"]

    async with db_session_factory() as db:
        db.add(Lineup(team_id=setup["team_id"], week=WEEK, year=YEAR, starters=[p2]))
        db.add(WeeklyScore(league_id=setup["league_id"], team_id=setup["team_id"], week=WEEK, year=YEAR,
                            total_score=10.0, lineup_data={"auto_lineup": True, "auto_starters": [p0, p1]}))
        await db.commit()

    r = await client.get(f"/teams/{setup['team_id']}/lineup", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
    assert set(r.json()["starters"]) == {p0, p1}


@pytest.mark.asyncio
async def test_get_lineup_best_ball_no_weekly_score_yet_is_all_bench(client, db_session_factory):
    setup = await _make_league_and_team(db_session_factory, best_ball_enabled=True)

    r = await client.get(f"/teams/{setup['team_id']}/lineup", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
    body = r.json()
    assert body["best_ball"] is True
    assert body["has_lineup_set"] is False
    assert body["starters"] == []
    assert all(p["is_starter"] is False for p in body["roster"])


@pytest.mark.asyncio
async def test_get_lineup_non_best_ball_unaffected(client, db_session_factory):
    """Regression pin: best_ball key present and False, everything else
    byte-for-byte the pre-existing Lineup-row-based behavior."""
    setup = await _make_league_and_team(db_session_factory, best_ball_enabled=False)
    p0, p1, _p2 = setup["players"]

    async with db_session_factory() as db:
        db.add(Lineup(team_id=setup["team_id"], week=WEEK, year=YEAR, starters=[p0, p1]))
        await db.commit()

    r = await client.get(f"/teams/{setup['team_id']}/lineup", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
    body = r.json()
    assert body["best_ball"] is False
    assert set(body["starters"]) == {p0, p1}
    assert body["has_lineup_set"] is True


@pytest.mark.asyncio
async def test_set_lineup_blocked_for_best_ball(client, db_session_factory):
    setup = await _make_league_and_team(db_session_factory, best_ball_enabled=True)
    p0 = setup["players"][0]

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.put(f"/teams/{setup['team_id']}/lineup", params={"week": WEEK, "year": YEAR},
                          json={"starters": [p0]})
    assert r.status_code == 400
    assert "Best-Ball" in r.json()["detail"]


@pytest.mark.asyncio
async def test_optimize_lineup_blocked_for_best_ball(client, db_session_factory):
    setup = await _make_league_and_team(db_session_factory, best_ball_enabled=True)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/teams/{setup['team_id']}/lineup/optimize", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 400
    assert "Best-Ball" in r.json()["detail"]


@pytest.mark.asyncio
async def test_set_and_optimize_lineup_unaffected_when_best_ball_disabled(client, db_session_factory):
    setup = await _make_league_and_team(db_session_factory, best_ball_enabled=False)
    p0 = setup["players"][0]

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.put(f"/teams/{setup['team_id']}/lineup", params={"week": WEEK, "year": YEAR},
                          json={"starters": [p0]})
    assert r.status_code == 200

    r = await client.post(f"/teams/{setup['team_id']}/lineup/optimize", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
