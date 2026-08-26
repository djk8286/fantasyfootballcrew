"""
Tests for top_performers_service.compute_top_performers -- Dashboard AI
Summaries initiative. Ranks every synced player (cross-league, not
scoped to any one league's custom scoring) by DEFAULT_SCORING for a
given week.
"""
import uuid
import pytest
from app.models.player import Player
from app.services.top_performers_service import compute_top_performers, TOP_N


async def _add_player(db, week, stats, position="RB", **kwargs):
    p = Player(
        id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), first_name="Test", last_name=f"Player{uuid.uuid4().hex[:4]}",
        position=position, team="XXX", week_stats={str(week): stats}, **kwargs,
    )
    db.add(p)
    return p


@pytest.mark.asyncio
async def test_ranks_players_by_default_scoring_highest_first(db_session_factory):
    async with db_session_factory() as db:
        big_week = await _add_player(db, 1, {"rush_yd": 200, "rush_td": 3})
        small_week = await _add_player(db, 1, {"rush_yd": 20})
        await db.commit()

    async with db_session_factory() as db:
        result = await compute_top_performers(week=1, year=2026, db=db)

    names = [p["name"] for p in result]
    assert names.index(f"Test {big_week.last_name}") < names.index(f"Test {small_week.last_name}")


@pytest.mark.asyncio
async def test_excludes_players_with_no_stats_for_that_week(db_session_factory):
    """Confirms a player who simply didn't play this week (no week_stats
    entry at all) is excluded outright, not scored as 0 and included."""
    async with db_session_factory() as db:
        played = await _add_player(db, 1, {"rush_yd": 50})
        db.add(Player(id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), first_name="Test",
                       last_name="Benched", position="RB", team="XXX", week_stats={}))
        await db.commit()

    async with db_session_factory() as db:
        result = await compute_top_performers(week=1, year=2026, db=db)

    names = {p["name"] for p in result}
    assert f"Test {played.last_name}" in names
    assert "Test Benched" not in names


@pytest.mark.asyncio
async def test_only_looks_at_the_requested_week(db_session_factory):
    async with db_session_factory() as db:
        p = Player(id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), first_name="Test", last_name="WeekTwo",
                   position="RB", team="XXX", week_stats={"2": {"rush_yd": 300}})
        db.add(p)
        await db.commit()

    async with db_session_factory() as db:
        week1_result = await compute_top_performers(week=1, year=2026, db=db)
        week2_result = await compute_top_performers(week=2, year=2026, db=db)

    assert "Test WeekTwo" not in {p["name"] for p in week1_result}
    assert "Test WeekTwo" in {p["name"] for p in week2_result}


@pytest.mark.asyncio
async def test_caps_at_top_n(db_session_factory):
    async with db_session_factory() as db:
        for i in range(TOP_N + 5):
            await _add_player(db, 1, {"rush_yd": 10 + i})
        await db.commit()

    async with db_session_factory() as db:
        result = await compute_top_performers(week=1, year=2026, db=db)

    assert len(result) == TOP_N
