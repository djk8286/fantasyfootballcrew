"""QA round 2 #2: season stats must not grow on every re-sync of the same week."""
import uuid
import pytest
from sqlalchemy import select

from app.models.player import Player
import app.services.sleeper_sync as ss


@pytest.mark.asyncio
async def test_resync_same_week_is_idempotent(db_session_factory, monkeypatch):
    weeks = {1: {"S1": {"rush_yd": 100.0, "rush_td": 1.0, "pos_rank_ppr": 3}},
             2: {"S1": {"rush_yd": 50.0, "pos_rank_ppr": 7}}}

    async def fake_fetch(year, week):
        return weeks[week]
    monkeypatch.setattr(ss, "fetch_weekly_stats", fake_fetch)

    async with db_session_factory() as db:
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="S1", first_name="A", last_name="B",
                      position="RB", stats_year=2026))
        await db.commit()
        for _ in range(5):  # the scheduler re-syncs the current week repeatedly
            await ss.sync_weekly_stats(db, 2026, 1)
        for _ in range(3):
            await ss.sync_weekly_stats(db, 2026, 2)

    async with db_session_factory() as db:
        p = (await db.execute(select(Player).where(Player.sleeper_id == "S1"))).scalar_one()
        assert p.stats["rush_yd"] == 150.0
        assert p.stats["rush_td"] == 1.0
        assert p.stats["pos_rank_ppr"] == 7  # ranks take the latest week, not summed
        assert set(p.week_stats) == {"1", "2"}


@pytest.mark.asyncio
async def test_rebuild_repairs_inflated_totals(db_session_factory):
    async with db_session_factory() as db:
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="S2", first_name="A", last_name="B",
                      position="RB", stats_year=2026, stats={"rush_yd": 776642.0},
                      week_stats={"1": {"rush_yd": 80.0}, "2": {"rush_yd": 20.0}}))
        await db.commit()
        changed = await ss.rebuild_season_stats_from_weeks(db)
        assert changed == 1
        assert await ss.rebuild_season_stats_from_weeks(db) == 0
    async with db_session_factory() as db:
        p = (await db.execute(select(Player).where(Player.sleeper_id == "S2"))).scalar_one()
        assert p.stats == {"rush_yd": 100.0}
