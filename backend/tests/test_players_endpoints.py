"""
Endpoint tests for GET /players' new sort_by param (Player Rankings Fix
initiative) -- rank/points/yards/touchdowns/projected, each with a fixed
best-first direction (see api/v1/players.py's SORT_VALUES). Also covers
/players/top-prospects now that it's a thin wrapper around the same
build_rank_by_id ranking code path list_players' sort_by=rank case uses,
rather than its own separate (formerly static-list-based) ranking.
"""
import uuid
import pytest
from app.models.player import Player


async def _add_players(db_session_factory, players: list[dict]):
    async with db_session_factory() as db:
        for kwargs in players:
            db.add(Player(id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), **kwargs))
        await db.commit()


@pytest.mark.asyncio
async def test_sort_by_rank_orders_best_production_first(client, db_session_factory):
    await _add_players(db_session_factory, [
        {"first_name": "Weak", "last_name": "Runner", "position": "RB",
         "last_season_stats": {"rush_yd": 200, "rush_td": 1}},
        {"first_name": "Star", "last_name": "Runner", "position": "RB",
         "last_season_stats": {"rush_yd": 1800, "rush_td": 18}},
    ])
    r = await client.get("/players", params={"sort_by": "rank", "position": "RB"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["first_name"] == "Star"
    assert body[1]["first_name"] == "Weak"


@pytest.mark.asyncio
async def test_sort_by_yards_orders_by_raw_last_season_yards(client, db_session_factory):
    await _add_players(db_session_factory, [
        {"first_name": "Low", "last_name": "Yards", "position": "WR",
         "last_season_stats": {"rec_yd": 300}},
        {"first_name": "High", "last_name": "Yards", "position": "WR",
         "last_season_stats": {"rec_yd": 1500}},
    ])
    r = await client.get("/players", params={"sort_by": "yards", "position": "WR"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["first_name"] == "High"
    assert body[0]["last_season_yards"] == 1500
    assert body[1]["first_name"] == "Low"


@pytest.mark.asyncio
async def test_sort_by_touchdowns_orders_by_raw_last_season_touchdowns(client, db_session_factory):
    await _add_players(db_session_factory, [
        {"first_name": "Few", "last_name": "TDs", "position": "RB",
         "last_season_stats": {"rush_td": 1}},
        {"first_name": "Many", "last_name": "TDs", "position": "RB",
         "last_season_stats": {"rush_td": 15}},
    ])
    r = await client.get("/players", params={"sort_by": "touchdowns", "position": "RB"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["first_name"] == "Many"
    assert body[0]["last_season_touchdowns"] == 15


@pytest.mark.asyncio
async def test_sort_by_points_orders_by_last_season_fantasy_points(client, db_session_factory):
    await _add_players(db_session_factory, [
        {"first_name": "Low", "last_name": "Scorer", "position": "WR",
         "last_season_stats": {"rec": 20, "rec_yd": 200, "rec_td": 1}},
        {"first_name": "High", "last_name": "Scorer", "position": "WR",
         "last_season_stats": {"rec": 90, "rec_yd": 1400, "rec_td": 10}},
    ])
    r = await client.get("/players", params={"sort_by": "points", "position": "WR"})
    assert r.status_code == 200
    assert r.json()[0]["first_name"] == "High"


@pytest.mark.asyncio
async def test_sort_by_projected_orders_by_synced_projection_and_nulls_sort_last(client, db_session_factory):
    await _add_players(db_session_factory, [
        {"first_name": "No", "last_name": "Projection", "position": "RB"},
        {"first_name": "Big", "last_name": "Projection", "position": "RB",
         "projected_stats": {"pts_ppr": 22.0, "rush_yd": 110, "rush_td": 1}, "projected_week": 1, "projected_year": 2026},
    ])
    r = await client.get("/players", params={"sort_by": "projected", "position": "RB"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["first_name"] == "Big"
    assert body[0]["projected_points"] is not None
    assert body[1]["first_name"] == "No"
    assert body[1]["projected_points"] is None


@pytest.mark.asyncio
async def test_sort_by_projected_ties_break_on_real_rank_not_db_order(client, db_session_factory):
    """Regression test for a real reported bug: with no real Sleeper
    projections synced yet (the whole pool ties at the same 0), the sort
    must not degrade to arbitrary DB-insertion order -- it must fall back
    to the real search_rank-based rank, so a genuine star still sorts
    above deep-bench names even with no projection data to sort by yet."""
    await _add_players(db_session_factory, [
        {"first_name": "Deep", "last_name": "Bench", "position": "RB", "search_rank": 3000},
        {"first_name": "Real", "last_name": "Star", "position": "RB", "search_rank": 2},
        {"first_name": "Mid", "last_name": "Tier", "position": "RB", "search_rank": 500},
    ])
    r = await client.get("/players", params={"sort_by": "projected", "position": "RB"})
    assert r.status_code == 200
    body = r.json()
    # None of them have a real projection -- all tie at 0 -- so the order
    # must come from search_rank (Star < Tier < Bench), not insertion order.
    assert [p["first_name"] for p in body] == ["Real", "Mid", "Deep"]


@pytest.mark.asyncio
async def test_unspecified_sort_by_is_unaffected(client, db_session_factory):
    """No sort_by -- unsorted DB-order behavior, unchanged from before
    this param existed."""
    await _add_players(db_session_factory, [
        {"first_name": "A", "last_name": "Player", "position": "TE"},
    ])
    r = await client.get("/players", params={"position": "TE"})
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_top_prospects_uses_same_data_driven_rank(client, db_session_factory):
    await _add_players(db_session_factory, [
        {"first_name": "Weak", "last_name": "Prospect", "position": "WR",
         "last_season_stats": {"rec_yd": 100}},
        {"first_name": "Star", "last_name": "Prospect", "position": "WR",
         "last_season_stats": {"rec_yd": 1600, "rec_td": 12, "rec": 100}},
        # DEF isn't in SKILL_POSITIONS -- must not appear.
        {"first_name": "Team", "last_name": "Defense", "position": "DEF"},
    ])
    r = await client.get("/players/top-prospects", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    names = [p["first_name"] for p in body]
    assert "Star" in names and "Weak" in names
    assert "Team" not in names
    assert names.index("Star") < names.index("Weak")
    assert body[names.index("Star")]["rank"] < body[names.index("Weak")]["rank"]
