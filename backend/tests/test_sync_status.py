"""GET /nfl/sync-status: last Sleeper and ESPN sync times for the
freshness chip. Public, timestamps only."""
from datetime import datetime, timedelta, timezone
import pytest

from app.api.v1 import nfl as nfl_module
from app.models.job_run import JobRun
from app.models.nfl_game import NFLGame


@pytest.fixture(autouse=True)
def _fresh_status(monkeypatch):
    nfl_module.reset_sync_status_cache()

    async def _state():
        return {"season": 2026, "week": 7, "season_type": "regular"}

    monkeypatch.setattr(nfl_module, "current_nfl_week", _state)
    yield
    nfl_module.reset_sync_status_cache()


def _run(job, finished, ok=True, error=None):
    return JobRun(job_name=job, started_at=finished - timedelta(seconds=2), finished_at=finished,
                  duration_ms=2000, success=ok, error=error)


def _at(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc).replace(microsecond=0)


@pytest.mark.asyncio
async def test_never_synced_reports_nulls_without_auth(client):
    r = await client.get("/nfl/sync-status")
    assert r.status_code == 200
    body = r.json()
    assert set(body["sources"]) == {"sleeper", "espn"}
    for src in body["sources"].values():
        assert src == {"last_success_at": None, "last_attempt_at": None, "last_attempt_ok": None}


@pytest.mark.asyncio
async def test_reports_last_success_and_a_failed_latest_attempt(client, db_session_factory):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    async with db_session_factory() as db:
        db.add_all([
            _run("sync_stats", now - timedelta(minutes=30)),
            _run("sync_stats", now - timedelta(minutes=14)),
            _run("sync_stats", now - timedelta(minutes=2), ok=False, error="HTTPError: sleeper 502 secret-host"),
            _run("sync_scoreboard", now - timedelta(minutes=5)),
            _run("prune_job_runs", now),
        ])
        await db.commit()

    body = (await client.get("/nfl/sync-status")).json()
    sleeper, espn = body["sources"]["sleeper"], body["sources"]["espn"]
    assert _at(sleeper["last_success_at"]) == now - timedelta(minutes=14)
    assert _at(sleeper["last_attempt_at"]) == now - timedelta(minutes=2)
    assert sleeper["last_attempt_ok"] is False
    assert _at(espn["last_success_at"]) == now - timedelta(minutes=5)
    assert espn["last_attempt_ok"] is True
    assert "secret-host" not in str(body)


@pytest.mark.asyncio
async def test_newer_game_row_counts_as_an_espn_sync(client, db_session_factory):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    async with db_session_factory() as db:
        db.add(_run("sync_scoreboard", now - timedelta(hours=3)))
        db.add(NFLGame(espn_event_id="9001", year=2026, week=7, season_type=2,
                       home_team="KC", home_team_name="Kansas City Chiefs",
                       away_team="BUF", away_team_name="Buffalo Bills",
                       status_state="pre", status_detail="Sun 1:00 PM", kickoff_at=now,
                       synced_at=now - timedelta(minutes=1)))
        await db.commit()

    espn = (await client.get("/nfl/sync-status")).json()["sources"]["espn"]
    assert _at(espn["last_success_at"]) == now - timedelta(minutes=1)
    assert _at(espn["last_attempt_at"]) == now - timedelta(hours=3)


@pytest.mark.asyncio
async def test_reports_season_type_and_caches_for_30s(client, db_session_factory):
    first = (await client.get("/nfl/sync-status")).json()
    assert first["season_type"] == "regular"
    assert first["sources"]["sleeper"]["last_success_at"] is None

    async with db_session_factory() as db:
        db.add(_run("sync_stats", datetime.now(timezone.utc)))
        await db.commit()
    # Served from the cache: the new run doesn't show up yet.
    assert (await client.get("/nfl/sync-status")).json() == first

    nfl_module.reset_sync_status_cache()
    after = (await client.get("/nfl/sync-status")).json()
    assert after["sources"]["sleeper"]["last_success_at"] is not None


@pytest.mark.asyncio
async def test_season_type_is_null_when_sleeper_state_fails(client, monkeypatch):
    async def _fail():
        raise RuntimeError("sleeper down")

    monkeypatch.setattr(nfl_module, "current_nfl_week", _fail)
    body = (await client.get("/nfl/sync-status")).json()
    assert body["season_type"] is None
    assert set(body["sources"]) == {"sleeper", "espn"}
