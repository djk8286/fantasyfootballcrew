"""Fantasy golf data layer (PR 1): models, constraints, defaults, flag."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.models import League, GolfTournament, Golfer, GolfFieldEntry, GolfPick, GolfTeamEventResult


def test_golf_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("GOLF_ENABLED", raising=False)
    assert Settings().GOLF_ENABLED is False


@pytest.mark.asyncio
async def test_existing_league_defaults_to_nfl(seed):
    async with seed["db_session_factory"]() as db:
        league = await db.get(League, seed["league_id"])
        assert league.sport == "nfl"


async def _event_and_golfer(db):
    t = GolfTournament(espn_event_id="401850916", name="Baycurrent Classic", season=2026,
                       start_date=datetime(2026, 10, 9, tzinfo=timezone.utc))
    g = Golfer(espn_athlete_id="4921329", full_name="Michael Brennan")
    db.add_all([t, g])
    await db.flush()
    return t, g


@pytest.mark.asyncio
async def test_golf_rows_and_defaults(seed):
    async with seed["db_session_factory"]() as db:
        t, g = await _event_and_golfer(db)
        db.add(GolfFieldEntry(tournament_id=t.id, golfer_id=g.id, tier=1, to_par=-16, position="1",
                              rounds=[{"round": 1, "strokes": 68, "to_par": -3}]))
        db.add(GolfPick(league_id=seed["league_id"], team_id=seed["team_a"], tournament_id=t.id, tier=1, golfer_id=g.id))
        db.add(GolfTeamEventResult(league_id=seed["league_id"], team_id=seed["team_a"], tournament_id=t.id, counted_to_par=-16))
        await db.commit()

    async with seed["db_session_factory"]() as db:
        t = (await db.execute(select(GolfTournament))).scalar_one()
        assert (t.is_major, t.status, t.tour) == (False, "scheduled", "pga")
        g = (await db.execute(select(Golfer))).scalar_one()
        assert g.is_amateur is False and g.season_points == 0
        fe = (await db.execute(select(GolfFieldEntry))).scalar_one()
        assert fe.status == "active" and fe.rounds[0]["strokes"] == 68
        r = (await db.execute(select(GolfTeamEventResult))).scalar_one()
        assert r.is_final is False and r.season_points == 0


@pytest.mark.asyncio
async def test_one_pick_per_tier_per_event(seed):
    async with seed["db_session_factory"]() as db:
        t, g = await _event_and_golfer(db)
        g2 = Golfer(espn_athlete_id="9", full_name="Other Golfer")
        db.add(g2)
        await db.flush()
        db.add(GolfPick(league_id=seed["league_id"], team_id=seed["team_a"], tournament_id=t.id, tier=1, golfer_id=g.id))
        db.add(GolfPick(league_id=seed["league_id"], team_id=seed["team_a"], tournament_id=t.id, tier=1, golfer_id=g2.id))
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_unique_espn_ids_and_field_entry(seed):
    async with seed["db_session_factory"]() as db:
        t, g = await _event_and_golfer(db)
        db.add(GolfFieldEntry(tournament_id=t.id, golfer_id=g.id))
        db.add(GolfFieldEntry(tournament_id=t.id, golfer_id=g.id))
        with pytest.raises(IntegrityError):
            await db.commit()
    async with seed["db_session_factory"]() as db:
        db.add(Golfer(espn_athlete_id="dup", full_name="A"))
        db.add(Golfer(espn_athlete_id="dup", full_name="B"))
        with pytest.raises(IntegrityError):
            await db.commit()
