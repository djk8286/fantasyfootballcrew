"""GET /nfl/sync-status: last Sleeper and ESPN sync times for the
freshness chip. Public, timestamps only."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.api.v1 import nfl as nfl_module
from app.core.limiter import limiter
from app.models.job_run import JobRun
from app.models.nfl_game import NFLGame
from app.services import nfl_state, scheduler


@pytest.fixture(autouse=True)
def _fresh_status(monkeypatch):
    nfl_module.reset_sync_status_cache()
    nfl_state.reset_nfl_state()
    limiter.reset()

    # The route must never reach Sleeper itself.
    async def _no_sleeper():
        raise AssertionError("sync-status called Sleeper")

    monkeypatch.setattr(nfl_module, "current_nfl_week", _no_sleeper)
    monkeypatch.setattr(nfl_module, "fetch_nfl_state", _no_sleeper)
    monkeypatch.setattr(scheduler, "fetch_nfl_state", _no_sleeper)
    nfl_state.record_nfl_state({"season": "2026", "week": "7", "season_type": "regular"})
    yield
    nfl_module.reset_sync_status_cache()
    nfl_state.reset_nfl_state()
    limiter.reset()


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
async def test_caches_sources_for_30s_but_stamps_generated_at_fresh(client, db_session_factory):
    first = (await client.get("/nfl/sync-status")).json()
    assert first["season_type"] == "regular"
    assert first["sources"]["sleeper"]["last_success_at"] is None

    async with db_session_factory() as db:
        db.add(_run("sync_stats", datetime.now(timezone.utc)))
        await db.commit()
    await asyncio.sleep(0.05)
    second = (await client.get("/nfl/sync-status")).json()
    # Sources come from the cache, so the new run doesn't show up yet...
    assert second["sources"] == first["sources"]
    # ...but generated_at is this response's own time, not the cache's.
    assert datetime.fromisoformat(second["generated_at"]) > datetime.fromisoformat(first["generated_at"])
    assert abs(datetime.fromisoformat(second["generated_at"]) - datetime.now(timezone.utc)) < timedelta(seconds=5)

    nfl_module.reset_sync_status_cache()
    after = (await client.get("/nfl/sync-status")).json()
    assert after["sources"]["sleeper"]["last_success_at"] is not None


@pytest.mark.asyncio
async def test_season_type_follows_the_scheduler_without_a_cache_delay(client):
    assert (await client.get("/nfl/sync-status")).json()["season_type"] == "regular"
    nfl_state.record_nfl_state({"season": "2026", "week": "1", "season_type": "post"})
    assert (await client.get("/nfl/sync-status")).json()["season_type"] == "post"


@pytest.mark.asyncio
async def test_season_type_is_null_before_the_scheduler_has_read_sleeper(client):
    nfl_state.reset_nfl_state()
    body = (await client.get("/nfl/sync-status")).json()
    assert body["season_type"] is None
    assert set(body["sources"]) == {"sleeper", "espn"}


@pytest.mark.asyncio
async def test_season_type_is_null_when_the_scheduler_value_is_old(client, monkeypatch):
    real = nfl_state.time.monotonic
    monkeypatch.setattr(nfl_state.time, "monotonic", lambda: real() + nfl_state.MAX_AGE_S + 1)
    assert (await client.get("/nfl/sync-status")).json()["season_type"] is None


@pytest.mark.parametrize("bad", [2, {"x": 1}, ["regular"], "Regular", "x" * 1_000_000, None, ""])
@pytest.mark.asyncio
async def test_unknown_season_type_reads_null_and_never_sticks(client, bad):
    nfl_state.record_nfl_state({"season": "2026", "week": "7", "season_type": bad})
    r = await client.get("/nfl/sync-status")
    assert r.status_code == 200
    assert r.json()["season_type"] is None
    assert len(r.content) < 2000
    # The next good read shows straight away; nothing bad was cached.
    nfl_state.record_nfl_state({"season": "2026", "week": "7", "season_type": "off"})
    assert (await client.get("/nfl/sync-status")).json()["season_type"] == "off"


def test_non_dict_state_records_null():
    nfl_state.record_nfl_state(["not", "a", "dict"])
    assert nfl_state.latest_season_type() is None


@pytest.mark.asyncio
async def test_scheduler_fetch_records_the_season_type(monkeypatch):
    monkeypatch.undo()  # the real fetch_nfl_state, Sleeper mocked below
    nfl_state.reset_nfl_state()
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"season": "2026", "week": 18, "season_type": "pre"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(scheduler.httpx, "AsyncClient",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))
    state = await scheduler.fetch_nfl_state()
    assert state["season_type"] == "pre"
    assert seen and seen[0].endswith("/state/nfl")
    assert nfl_state.latest_season_type() == "pre"


@pytest.mark.asyncio
async def test_cold_cache_burst_reads_job_runs_once(client, monkeypatch):
    calls = {"n": 0}
    real = nfl_module.get_sync_status

    async def counting(db):
        calls["n"] += 1
        await asyncio.sleep(0.2)
        return await real(db)

    monkeypatch.setattr(nfl_module, "get_sync_status", counting)
    rs = await asyncio.gather(*[client.get("/nfl/sync-status") for _ in range(30)])
    assert {r.status_code for r in rs} == {200}
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_rate_limited_per_client(client):
    codes = [(await client.get("/nfl/sync-status")).status_code for _ in range(121)]
    assert codes[:120] == [200] * 120
    assert codes[120] == 429
