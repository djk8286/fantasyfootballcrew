"""
Tests for nfl_projections_service -- Sleeper's projections endpoint
(GET /v1/projections/nfl/{season_type}/{year}/{week}, confirmed real
directly against the live API while building this: 9,418 entries, most
of them "no real projection" placeholders with only adp_dd_ppr, ~975
with genuine per-stat projections). Only ever exposes WEEKLY
projections -- no season-aggregate endpoint exists -- so this is stored
and used as a per-game figure, never a fabricated season total (see
Player.projected_stats). sync_week_projections' upsert behavior is
tested with httpx mocked out, same technique test_nfl_schedule_service.py
uses.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.player import Player
from app.services.nfl_projections_service import sync_week_projections


@pytest.mark.asyncio
async def test_sync_week_projections_updates_matched_players(db_session_factory, monkeypatch):
    async def fake_fetch(year, week, season_type):
        return {
            "sleeper-1": {"pts_ppr": 24.5, "rush_yd": 90, "rush_td": 1},
            # Placeholder-only entry -- no real projection, must be skipped.
            "sleeper-2": {"adp_dd_ppr": 55.0},
            # No matching synced Player -- must be silently skipped, not error.
            "sleeper-unknown": {"pts_ppr": 12.0, "rec_yd": 80},
        }

    import app.services.nfl_projections_service as mod
    monkeypatch.setattr(mod, "fetch_week_projections", fake_fetch)

    async with db_session_factory() as db:
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="sleeper-1", first_name="Star",
                       last_name="Runner", position="RB"))
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="sleeper-2", first_name="Deep",
                       last_name="Bench", position="WR"))
        await db.commit()

    async with db_session_factory() as db:
        count = await sync_week_projections(db, 2026, 1)
        assert count == 1  # only sleeper-1 had a real projection AND a matching player

    async with db_session_factory() as db:
        result = await db.execute(select(Player).where(Player.sleeper_id == "sleeper-1"))
        player = result.scalar_one()
        assert player.projected_stats == {"pts_ppr": 24.5, "rush_yd": 90, "rush_td": 1}
        assert player.projected_week == 1
        assert player.projected_year == 2026

        result = await db.execute(select(Player).where(Player.sleeper_id == "sleeper-2"))
        untouched = result.scalar_one()
        assert untouched.projected_stats is None


@pytest.mark.asyncio
async def test_sync_week_projections_no_meaningful_entries_returns_zero(db_session_factory, monkeypatch):
    async def fake_fetch(year, week, season_type):
        return {"sleeper-1": {"adp_dd_ppr": 10.0}, "sleeper-2": {"pos_adp_dd_ppr": 3.0}}

    import app.services.nfl_projections_service as mod
    monkeypatch.setattr(mod, "fetch_week_projections", fake_fetch)

    async with db_session_factory() as db:
        count = await sync_week_projections(db, 2026, 1)
        assert count == 0


@pytest.mark.asyncio
async def test_sync_week_projections_overwrites_stale_projection(db_session_factory, monkeypatch):
    """A second sync for a new week should replace last week's snapshot,
    not accumulate alongside it -- there's only ever one current
    per-game projection per player."""
    async def fake_fetch(year, week, season_type):
        return {"sleeper-1": {"pts_ppr": 30.0, "rush_yd": 100}}

    import app.services.nfl_projections_service as mod
    monkeypatch.setattr(mod, "fetch_week_projections", fake_fetch)

    async with db_session_factory() as db:
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="sleeper-1", first_name="Star",
                       last_name="Runner", position="RB",
                       projected_stats={"pts_ppr": 10.0}, projected_week=1, projected_year=2026))
        await db.commit()

    async with db_session_factory() as db:
        count = await sync_week_projections(db, 2026, 2)
        assert count == 1

    async with db_session_factory() as db:
        result = await db.execute(select(Player).where(Player.sleeper_id == "sleeper-1"))
        player = result.scalar_one()
        assert player.projected_stats == {"pts_ppr": 30.0, "rush_yd": 100}
        assert player.projected_week == 2
