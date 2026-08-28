"""
Regression test for a real reported bug: retired players (Todd Gurley,
confirmed by name) still showing up ranked in the draft pool/players
list. Root cause, confirmed directly against the real Sleeper API:
Sleeper's own active/team fields are NOT reliable for "is this player
actually on an NFL roster right now" -- long-retired players still carry
active=true and a real search_rank (Gurley: active=true, search_rank=27;
Tom Brady: active=true, search_rank=74), and team isn't reliable either
(Ben Roethlisberger, retired since 2022, still shows team="PIT"). Every
one of those three had depth_chart_position=null though, while every
real current starter checked had a real one -- sync_players_to_db now
only trusts search_rank when depth_chart_position is also present.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.player import Player
from app.services.sleeper_sync import sync_players_to_db


@pytest.mark.asyncio
async def test_search_rank_discarded_without_depth_chart_position_new_player(db_session_factory, monkeypatch):
    async def fake_fetch():
        return {
            "2315": {
                "first_name": "Todd", "last_name": "Gurley", "position": "RB",
                "team": None, "active": True, "search_rank": 27,
                "depth_chart_position": None,
            },
            "4034": {
                "first_name": "Christian", "last_name": "McCaffrey", "position": "RB",
                "team": "SF", "active": True, "search_rank": 5,
                "depth_chart_position": "RB",
            },
        }

    import app.services.sleeper_sync as mod
    monkeypatch.setattr(mod, "fetch_all_players", fake_fetch)

    async with db_session_factory() as db:
        count = await sync_players_to_db(db)
        assert count == 2

    async with db_session_factory() as db:
        gurley = (await db.execute(select(Player).where(Player.sleeper_id == "2315"))).scalar_one()
        mccaffrey = (await db.execute(select(Player).where(Player.sleeper_id == "4034"))).scalar_one()
        assert gurley.search_rank is None
        assert mccaffrey.search_rank == 5


@pytest.mark.asyncio
async def test_search_rank_discarded_without_depth_chart_position_existing_player(db_session_factory, monkeypatch):
    """Same check on the UPDATE path, not just player creation -- a
    player who previously had a real search_rank must lose it (go back
    to None) the moment Sleeper stops carrying a depth_chart_position for
    them, not keep stale data forever."""
    async with db_session_factory() as db:
        db.add(Player(id=str(uuid.uuid4()), sleeper_id="2315", first_name="Todd", last_name="Gurley",
                       position="RB", search_rank=27))
        await db.commit()

    async def fake_fetch():
        return {
            "2315": {
                "first_name": "Todd", "last_name": "Gurley", "position": "RB",
                "team": None, "active": True, "search_rank": 27,
                "depth_chart_position": None,
            },
        }

    import app.services.sleeper_sync as mod
    monkeypatch.setattr(mod, "fetch_all_players", fake_fetch)

    async with db_session_factory() as db:
        await sync_players_to_db(db)

    async with db_session_factory() as db:
        gurley = (await db.execute(select(Player).where(Player.sleeper_id == "2315"))).scalar_one()
        assert gurley.search_rank is None
