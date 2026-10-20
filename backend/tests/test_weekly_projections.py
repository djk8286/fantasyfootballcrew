"""Weekly projections: the Sleeper sync into player_projections, the
switch, league-scored projections in GET /lineup, and auto-fill ranking
by projection."""
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select

import app.services.nfl_projections_service as proj
from app.core.config import settings
from app.models.league import DraftStatus, League, LeagueType
from app.models.nfl_game import NFLGame
from app.models.player import Player
from app.models.player_projection import PlayerProjection
from app.models.team import Team
from app.models.user import User
from app.services.auth_service import create_access_token

YEAR, WEEK = 2026, 7
BACKEND = Path(__file__).resolve().parent.parent


def _fake(by_week):
    async def fetch(year, week, season_type="regular"):
        return by_week[week]
    return fetch


async def _player(db, sleeper_id, **kw):
    p = Player(id=str(uuid.uuid4()), sleeper_id=sleeper_id, first_name=sleeper_id, last_name="X",
               position=kw.pop("position", "RB"), **kw)
    db.add(p)
    return p


# ─── Sync ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_stores_the_week_and_replaces_it_on_the_next_pass(db_session_factory, monkeypatch):
    async with db_session_factory() as db:
        a = await _player(db, "a")
        b = await _player(db, "b")
        await db.commit()
        a_id, b_id = a.id, b.id

    monkeypatch.setattr(proj, "fetch_week_projections", _fake({WEEK: {"a": {"rush_yd": 80}, "b": {"rec_yd": 50}}}))
    async with db_session_factory() as db:
        assert await proj.sync_week_projections(db, YEAR, WEEK) == 2

    # b gets ruled out, so Sleeper drops him to a placeholder.
    monkeypatch.setattr(proj, "fetch_week_projections", _fake({WEEK: {"a": {"rush_yd": 95}, "b": {"adp_dd_ppr": 40}}}))
    async with db_session_factory() as db:
        assert await proj.sync_week_projections(db, YEAR, WEEK) == 1
        got = await proj.load_projections(db, [a_id, b_id], YEAR, WEEK)
    assert got == {a_id: {"rush_yd": 95}}


@pytest.mark.asyncio
async def test_a_player_on_bye_loses_last_weeks_projection(db_session_factory, monkeypatch):
    """Prod showed Josh Allen projected 25.1 in Buffalo's bye week. The
    old sync skipped placeholder entries and never cleared the old value."""
    async with db_session_factory() as db:
        await _player(db, "allen", position="QB", projected_stats={"pass_yd": 260}, projected_week=6, projected_year=YEAR)
        await db.commit()

    monkeypatch.setattr(proj, "fetch_week_projections", _fake({WEEK: {"allen": {"adp_dd_ppr": 1000.0}}}))
    async with db_session_factory() as db:
        await proj.sync_week_projections(db, YEAR, WEEK)

    async with db_session_factory() as db:
        allen = (await db.execute(select(Player).where(Player.sleeper_id == "allen"))).scalar_one()
    assert allen.projected_stats is None and allen.projected_week is None


@pytest.mark.asyncio
async def test_next_week_sync_leaves_the_current_week_snapshot_alone(db_session_factory, monkeypatch):
    async with db_session_factory() as db:
        p = await _player(db, "a", projected_stats={"rush_yd": 80}, projected_week=WEEK, projected_year=YEAR)
        await db.commit()
        pid = p.id

    monkeypatch.setattr(proj, "fetch_week_projections", _fake({WEEK + 1: {"a": {"rush_yd": 10}}}))
    async with db_session_factory() as db:
        await proj.sync_week_projections(db, YEAR, WEEK + 1, update_players=False)
        player = await db.get(Player, pid)
        assert player.projected_week == WEEK and player.projected_stats == {"rush_yd": 80}
        assert await proj.load_projections(db, [pid], YEAR, WEEK + 1) == {pid: {"rush_yd": 10}}


@pytest.mark.asyncio
async def test_scheduler_syncs_this_week_and_next_and_respects_the_switch(monkeypatch):
    import app.services.scheduler as sched
    calls = []

    async def fake_state():
        return {"season": str(YEAR), "week": WEEK, "season_type": "regular"}

    async def fake_sync(db, year, week, season_type="regular", update_players=True):
        calls.append((week, update_players))
        return 0

    monkeypatch.setattr(sched, "fetch_nfl_state", fake_state)
    monkeypatch.setattr(sched.nfl_projections_service, "sync_week_projections", fake_sync)

    monkeypatch.setattr(settings, "SLEEPER_PROJECTIONS_ENABLED", False)
    await sched._sync_projections_once()
    assert calls == []

    monkeypatch.setattr(settings, "SLEEPER_PROJECTIONS_ENABLED", True)
    await sched._sync_projections_once()
    assert calls == [(WEEK, True), (WEEK + 1, False)]


# ─── Lineup payload and auto-fill ───────────────────────────────────────

SCORING = {"rushing": {"rush_yd": 0.1, "rush_td": 6}, "receiving": {"rec_yd": 0.1}}
SLOTS = {"QB": 0, "RB": 1, "WR": 0, "TE": 0, "FLEX": 0, "SUPERFLEX": 0, "K": 0, "DEF": 0}


def _game(home, away):
    return NFLGame(id=str(uuid.uuid4()), espn_event_id=str(uuid.uuid4()), week=WEEK, year=YEAR, season_type=2,
                   home_team=home, home_team_name=home, away_team=away, away_team_name=away,
                   status_state="pre", status_detail="", completed=False,
                   kickoff_at=datetime.now(timezone.utc) + timedelta(days=3))


async def _league(db_session_factory):
    """Two teams. Ours has a star by season total who projects poorly this
    week, a lesser back who projects well, an unprojected back and a back
    on bye (LAC has no game)."""
    async with db_session_factory() as db:
        owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        league = League(id=str(uuid.uuid4()), name="L", commissioner_id=owner.id, league_type=LeagueType.STANDARD,
                        draft_status=DraftStatus.COMPLETED, scoring_config=SCORING, roster_slots=SLOTS)
        db.add_all([owner, league])
        await db.flush()
        star = await _player(db, "star", team="KC", stats_year=YEAR, stats={"rush_yd": 900})
        hot = await _player(db, "hot", team="LV", stats_year=YEAR, stats={"rush_yd": 300})
        none_ = await _player(db, "none", team="KC", stats_year=YEAR, stats={"rush_yd": 100})
        bye = await _player(db, "bye", team="LAC", stats_year=YEAR, stats={"rush_yd": 500})
        opp_rb = await _player(db, "opp", team="LV", stats_year=YEAR, stats={"rush_yd": 50})
        mine = Team(id=str(uuid.uuid4()), name="Mine", league_id=league.id, owner_id=owner.id,
                    roster=[star.id, hot.id, none_.id, bye.id], roster_version=0)
        theirs = Team(id=str(uuid.uuid4()), name="Theirs", league_id=league.id, roster=[opp_rb.id], roster_version=0)
        db.add_all([mine, theirs, _game("KC", "LV")])
        db.add_all([
            PlayerProjection(player_id=star.id, year=YEAR, week=WEEK, stats={"rush_yd": 40}),
            PlayerProjection(player_id=hot.id, year=YEAR, week=WEEK, stats={"rush_yd": 110, "rush_td": 1}),
            PlayerProjection(player_id=bye.id, year=YEAR, week=WEEK, stats={"rush_yd": 999}),
            PlayerProjection(player_id=opp_rb.id, year=YEAR, week=WEEK, stats={"rush_yd": 70}),
        ])
        await db.commit()
        token = create_access_token({"sub": owner.id, "email": owner.email})
        return {"team": mine.id, "theirs": theirs.id, "auth": {"Authorization": f"Bearer {token}"},
                "ids": {"star": star.id, "hot": hot.id, "none": none_.id, "bye": bye.id}}


PARAMS = {"week": WEEK, "year": YEAR}


@pytest.mark.asyncio
async def test_lineup_shows_league_scored_projections_and_both_matchup_totals(client, db_session_factory):
    s = await _league(db_session_factory)
    r = await client.get(f"/teams/{s['team']}/lineup", params=PARAMS)
    assert r.status_code == 200
    body = r.json()
    by = {p["id"]: p["projected_points"] for p in body["roster"]}
    assert by[s["ids"]["star"]] == 4.0
    assert by[s["ids"]["hot"]] == 17.0
    assert by[s["ids"]["none"]] is None
    assert by[s["ids"]["bye"]] == 0.0  # no game, whatever Sleeper says

    # The total is the projection of whoever fills the one RB slot now.
    starter = body["slots"][0]["player_id"]
    mine = by[starter] or 0.0
    assert body["projected_total"] == mine
    assert body["matchup"] == {"opponent_team_id": s["theirs"], "opponent_name": "Theirs",
                               "projected": mine, "opponent_projected": 7.0}


@pytest.mark.asyncio
async def test_switch_off_hides_projections(client, db_session_factory, monkeypatch):
    s = await _league(db_session_factory)
    monkeypatch.setattr(settings, "SLEEPER_PROJECTIONS_ENABLED", False)
    body = (await client.get(f"/teams/{s['team']}/lineup", params=PARAMS)).json()
    assert body["projected_total"] is None
    assert body["matchup"]["projected"] is None
    assert all(p["projected_points"] is None for p in body["roster"])


@pytest.mark.asyncio
async def test_auto_fill_starts_the_best_projection_not_the_best_season(client, db_session_factory):
    s = await _league(db_session_factory)
    r = await client.post(f"/teams/{s['team']}/lineup/optimize", params=PARAMS, headers=s["auth"])
    assert r.status_code == 200, r.text
    assert r.json()["ranked_by"] == "projection"
    assert r.json()["starters"] == [s["ids"]["hot"]]


@pytest.mark.asyncio
async def test_auto_fill_falls_back_to_season_totals_without_projections(client, db_session_factory, monkeypatch):
    s = await _league(db_session_factory)
    monkeypatch.setattr(settings, "SLEEPER_PROJECTIONS_ENABLED", False)
    r = await client.post(f"/teams/{s['team']}/lineup/optimize", params=PARAMS, headers=s["auth"])
    assert r.json()["ranked_by"] == "season"
    assert r.json()["starters"] == [s["ids"]["star"]]


# ─── Migration ──────────────────────────────────────────────────────────

def _alembic(db_path, *args):
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True,
                   capture_output=True, timeout=120)


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    finally:
        conn.close()


def test_projections_migration_chains_after_lineup_slots_and_round_trips(tmp_path):
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_revision("c3e8a1d5f7b2").down_revision == "b7d1e4f9a2c6"
    db = tmp_path / "p.db"
    _alembic(db, "upgrade", "c3e8a1d5f7b2")
    assert "player_projections" in _tables(db)
    _alembic(db, "downgrade", "b7d1e4f9a2c6")
    assert "player_projections" not in _tables(db)
