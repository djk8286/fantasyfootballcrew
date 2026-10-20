"""QA post-deploy retest 2026-10-19: default lineups skip ruled-out
players in any week still being played, a lineup week with no synced
games is fetched on demand (WSH -> WAS), the scheduler syncs next week
too, the AI lineup prompt carries the league's own slots, and nobody but
the team's owners or commissioners can change its lineup."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.models.league import League
from app.models.lineup import Lineup
from app.models.nfl_game import NFLGame
from app.models.player import Player
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services import nfl_schedule_service, scheduler
from app.services.ai_service import AIService
from app.services.auth_service import create_access_token
from app.services.standings_service import calculate_week
from tests.test_lineup_slots import PARAMS, WEEK, YEAR, _get, _seed


async def _set_injury(db_session_factory, player_id, status):
    async with db_session_factory() as db:
        await db.execute(update(Player).where(Player.id == player_id).values(injury_status=status))
        await db.commit()


async def _finish_all_games(db_session_factory):
    async with db_session_factory() as db:
        await db.execute(update(NFLGame).values(status_state="post", completed=True,
                                                kickoff_at=datetime.now(timezone.utc) - timedelta(days=1)))
        await db.commit()


# ─── Default lineup skips Out players while the week is still live ──────

@pytest.mark.asyncio
async def test_default_lineup_skips_out_player_after_kickoff_when_nothing_is_frozen(client, db_session_factory):
    """A league drafted mid-week (first kickoff already passed) used to get
    a default that started its best WR even though he was Out."""
    s = await _seed(db_session_factory, sf_started=True)
    await _set_injury(db_session_factory, s["ids"]["WR1"], "Out")
    body = await _get(client, s)
    assert body["has_lineup_set"] is False
    assert s["ids"]["WR1"] not in body["default_starters"]
    assert s["ids"]["WR2"] in body["default_starters"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["IR", "Sus", "PUP"])
async def test_default_lineup_skips_other_inactive_statuses(client, db_session_factory, status):
    s = await _seed(db_session_factory, sf_started=True)
    await _set_injury(db_session_factory, s["ids"]["QB1"], status)
    body = await _get(client, s)
    assert s["ids"]["QB1"] not in body["default_starters"]
    assert s["ids"]["QB2"] in body["default_starters"]


@pytest.mark.asyncio
async def test_finished_week_recompute_does_not_filter_on_todays_injury(client, db_session_factory):
    s = await _seed(db_session_factory)
    await _finish_all_games(db_session_factory)
    await _set_injury(db_session_factory, s["ids"]["WR1"], "Out")
    body = await _get(client, s)
    assert s["ids"]["WR1"] in body["default_starters"]


@pytest.mark.asyncio
async def test_saved_lineup_with_out_player_is_left_alone(client, db_session_factory):
    s = await _seed(db_session_factory, sf_started=True, legacy_starters=["QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "K1", "DEF1"])
    await _set_injury(db_session_factory, s["ids"]["WR1"], "Out")
    body = await _get(client, s)
    assert body["has_lineup_set"] is True
    assert s["ids"]["WR1"] in body["starters"]


@pytest.mark.asyncio
async def test_calculate_week_default_skips_out_player_after_kickoff(db_session_factory):
    s = await _seed(db_session_factory, sf_started=True)
    await _set_injury(db_session_factory, s["ids"]["WR1"], "Out")
    async with db_session_factory() as db:
        team_league = (await db.execute(select(League))).scalars().first()
        await calculate_week(team_league.id, WEEK, YEAR, db, sleeper_stats={})
    async with db_session_factory() as db:
        ws = (await db.execute(select(WeeklyScore).where(WeeklyScore.team_id == s["team"]))).scalar_one()
        assert ws.lineup_data["lineup_source"] == "default"
        assert s["ids"]["WR1"] not in ws.lineup_data["default_starters"]
        assert s["ids"]["WR2"] in ws.lineup_data["default_starters"]


@pytest.mark.asyncio
async def test_calculate_week_keeps_a_default_frozen_at_kickoff(db_session_factory):
    s = await _seed(db_session_factory, sf_started=True)
    async with db_session_factory() as db:
        league = (await db.execute(select(League))).scalars().first()
        await calculate_week(league.id, WEEK, YEAR, db, sleeper_stats={})
    await _set_injury(db_session_factory, s["ids"]["WR1"], "Out")
    async with db_session_factory() as db:
        await calculate_week(league.id, WEEK, YEAR, db, sleeper_stats={})
    async with db_session_factory() as db:
        ws = (await db.execute(select(WeeklyScore).where(WeeklyScore.team_id == s["team"]))).scalar_one()
        assert s["ids"]["WR1"] in ws.lineup_data["default_starters"]  # frozen, not reshuffled mid-week


# ─── Missing week's games are fetched on demand ─────────────────────────

def _espn_payload(week):
    kickoff = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%MZ")

    def comp(abbr, side):
        return {"homeAway": side, "team": {"abbreviation": abbr, "displayName": abbr}, "score": "0"}

    def event(eid, home, away):
        return {"id": eid, "date": kickoff, "status": {"type": {"state": "pre", "shortDetail": "Sun 1:00 PM", "completed": False}},
                "competitions": [{"competitors": [comp(home, "home"), comp(away, "away")]}]}

    return {"season": {"year": YEAR, "type": 2}, "week": {"number": week},
            "events": [event(f"e{week}a", "KC", "WSH"), event(f"e{week}b", "SF", "SEA")]}


@pytest.mark.asyncio
async def test_lineup_for_unsynced_week_fetches_games_and_maps_wsh(client, db_session_factory, monkeypatch):
    s = await _seed(db_session_factory)
    calls = []

    async def fake_fetch(year, week, season_type):
        calls.append(week)
        return _espn_payload(week)

    monkeypatch.setattr(nfl_schedule_service, "ON_DEMAND_SYNC", True)
    monkeypatch.setattr(nfl_schedule_service, "fetch_week_scoreboard", fake_fetch)
    r = await client.get(f"/teams/{s['team']}/lineup", params={"week": WEEK + 1, "year": YEAR})
    assert r.status_code == 200
    body = r.json()
    assert calls == [WEEK + 1]
    assert body["schedule_known"] is True
    qb1 = next(p for p in body["roster"] if p["id"] == s["ids"]["QB1"])
    assert qb1["game"]["opponent"] == "WAS" and qb1["game"]["home"] is True and qb1["game"]["kickoff_at"]
    rb3 = next(p for p in body["roster"] if p["id"] == s["ids"]["RB3"])
    assert rb3["on_bye"] is True  # LAC has no game that week

    # Stored now: the next read doesn't refetch.
    await client.get(f"/teams/{s['team']}/lineup", params={"week": WEEK + 1, "year": YEAR})
    assert calls == [WEEK + 1]


@pytest.mark.asyncio
async def test_failed_on_demand_fetch_still_returns_lineup_and_backs_off(client, db_session_factory, monkeypatch):
    s = await _seed(db_session_factory)
    calls = []

    async def boom(year, week, season_type):
        calls.append(week)
        raise RuntimeError("espn down")

    monkeypatch.setattr(nfl_schedule_service, "ON_DEMAND_SYNC", True)
    monkeypatch.setattr(nfl_schedule_service, "fetch_week_scoreboard", boom)
    for _ in range(2):
        r = await client.get(f"/teams/{s['team']}/lineup", params={"week": WEEK + 2, "year": YEAR})
        assert r.status_code == 200 and r.json()["schedule_known"] is False
    assert calls == [WEEK + 2]


@pytest.mark.asyncio
async def test_scheduler_scoreboard_sync_also_syncs_next_week(db_session_factory, monkeypatch):
    synced = []

    async def fake_sync(year, week, season_type, db):
        synced.append(week)
        return 1

    monkeypatch.setattr(scheduler, "async_session", db_session_factory)
    monkeypatch.setattr(nfl_schedule_service, "sync_week_scoreboard", fake_sync)
    await scheduler._sync_current_week_scoreboard_once(YEAR, 6)
    assert synced == [6, 7]
    synced.clear()
    await scheduler._sync_current_week_scoreboard_once(YEAR, 18)
    assert synced == [18]


# ─── AI lineup prompt uses the league's own slots ───────────────────────

@pytest.mark.asyncio
async def test_lineup_prompt_inputs_carry_league_roster_slots(db_session_factory):
    from app.api.v1 import ai as ai_module
    s = await _seed(db_session_factory)
    async with db_session_factory() as db:
        league = (await db.execute(select(League))).scalars().first()
        league.roster_slots = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 0, "SUPERFLEX": 1, "K": 0, "DEF": 1}
        await db.commit()
        from app.models.team import Team
        team = (await db.execute(select(Team).where(Team.id == s["team"]))).scalar_one()
        inputs = await ai_module._lineup_prompt_inputs(team, league, db)
    assert inputs["roster_slots"] == {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "SUPERFLEX": 1, "DEF": 1}
    wr3 = inputs["roster"][s["ids"]["WR3"]]
    assert wr3["injury_status"] == "Out"


@pytest.mark.asyncio
async def test_lineup_prompt_renders_the_slots():
    service = AIService()
    captured = {}

    async def spy(prompt):
        captured["prompt"] = prompt
        return "ok"

    service._call_llm = spy
    await service.analyze_lineup(roster={}, opponent_roster={}, matchups={}, scoring={},
                                 roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1})
    p = captured["prompt"]
    assert '"FLEX": 1' in p and '"K": 1' in p and "exactly these slots" in p


# ─── Lineup writes are owner/commissioner only ──────────────────────────

async def _stranger_auth(db_session_factory):
    async with db_session_factory() as db:
        u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"x{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(u)
        await db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'email': u.email})}"}


@pytest.mark.asyncio
async def test_non_owner_non_commissioner_cannot_set_or_autofill_lineup(client, db_session_factory):
    s = await _seed(db_session_factory)
    auth = await _stranger_auth(db_session_factory)
    starters = [s["ids"][k] for k in ("QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "K1", "DEF1")]
    r = await client.put(f"/teams/{s['team']}/lineup", params=PARAMS, json={"starters": starters}, headers=auth)
    assert r.status_code == 403
    r = await client.post(f"/teams/{s['team']}/lineup/optimize", params=PARAMS, headers=auth)
    assert r.status_code == 403
    r = await client.put(f"/teams/{s['team']}/lineup", params=PARAMS, json={"starters": starters})
    assert r.status_code == 401
    async with db_session_factory() as db:
        assert (await db.execute(select(Lineup).where(Lineup.team_id == s["team"]))).scalar_one_or_none() is None
    # The owner still can.
    r = await client.put(f"/teams/{s['team']}/lineup", params=PARAMS, json={"starters": starters}, headers=s["auth"])
    assert r.status_code == 200
