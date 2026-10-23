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
    # Other tests fill the /current-week cache, which season_type falls back to.
    monkeypatch.setattr(nfl_module, "_state_cache", None)
    monkeypatch.setattr(nfl_module, "_state_cache_at", 0.0)
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


def _slow_db(monkeypatch, delay=0.0, exc=None):
    calls = {"n": 0}
    real = nfl_module.get_sync_status

    async def wrapped(db):
        calls["n"] += 1
        await asyncio.sleep(delay)
        if exc is not None:
            raise exc
        return await real(db)

    monkeypatch.setattr(nfl_module, "get_sync_status", wrapped)
    return calls


@pytest.mark.asyncio
async def test_expired_cache_serves_the_stale_copy_while_one_request_refills(client, monkeypatch):
    assert (await client.get("/nfl/sync-status")).status_code == 200
    calls = _slow_db(monkeypatch, delay=0.5)
    nfl_module._sync_cache_at -= nfl_module.SYNC_STATUS_TTL + 1
    t0 = asyncio.get_running_loop().time()
    refill = asyncio.create_task(client.get("/nfl/sync-status"))
    await asyncio.sleep(0.05)
    others = await asyncio.gather(*[client.get("/nfl/sync-status") for _ in range(20)])
    assert {r.status_code for r in others} == {200}
    # The others didn't wait for the slow refill.
    assert asyncio.get_running_loop().time() - t0 < 0.4
    assert (await refill).status_code == 200
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_db_timeout_serves_stale_copy_or_503_when_there_is_none(client, monkeypatch):
    monkeypatch.setattr(nfl_module, "SYNC_STATUS_DB_TIMEOUT", 0.1)
    original = nfl_module.get_sync_status
    # Cold cache and a stuck database: 503, and queued requests fail fast.
    calls = _slow_db(monkeypatch, delay=5)
    t0 = asyncio.get_running_loop().time()
    rs = await asyncio.gather(*[client.get("/nfl/sync-status") for _ in range(5)])
    assert {r.status_code for r in rs} == {503}
    assert calls["n"] == 1
    assert asyncio.get_running_loop().time() - t0 < 1.0

    # The database recovers: the next request refills.
    monkeypatch.setattr(nfl_module, "get_sync_status", original)
    assert (await client.get("/nfl/sync-status")).status_code == 200

    # Expired cache, database stuck again: the old copy is served.
    _slow_db(monkeypatch, delay=5)
    nfl_module._sync_cache_at -= nfl_module.SYNC_STATUS_TTL + 1
    r = await client.get("/nfl/sync-status")
    assert r.status_code == 200
    assert set(r.json()["sources"]) == {"sleeper", "espn"}


@pytest.mark.asyncio
async def test_db_error_serves_stale_copy_and_does_not_leak(client, monkeypatch):
    assert (await client.get("/nfl/sync-status")).status_code == 200
    _slow_db(monkeypatch, exc=RuntimeError("boom secret-dsn"))
    nfl_module._sync_cache_at -= nfl_module.SYNC_STATUS_TTL + 1
    r = await client.get("/nfl/sync-status")
    assert r.status_code == 200
    assert "secret-dsn" not in r.text


@pytest.mark.asyncio
async def test_season_type_falls_back_to_a_recent_current_week_cache(client, monkeypatch):
    nfl_state.reset_nfl_state()
    now = nfl_module.time.monotonic()
    monkeypatch.setattr(nfl_module, "_state_cache", {"season": 2026, "week": 7, "season_type": "post"})
    monkeypatch.setattr(nfl_module, "_state_cache_at", now)
    assert (await client.get("/nfl/sync-status")).json()["season_type"] == "post"
    # Old or unknown values don't count.
    monkeypatch.setattr(nfl_module, "_state_cache_at", now - nfl_state.MAX_AGE_S - 1)
    assert (await client.get("/nfl/sync-status")).json()["season_type"] is None
    monkeypatch.setattr(nfl_module, "_state_cache", {"season": 2026, "week": 7, "season_type": "weird"})
    monkeypatch.setattr(nfl_module, "_state_cache_at", now)
    assert (await client.get("/nfl/sync-status")).json()["season_type"] is None


class _StopScheduler(BaseException):
    pass


@pytest.mark.asyncio
async def test_scheduler_primes_nfl_state_before_the_slow_startup_syncs(monkeypatch):
    order = []

    async def fake_fetch():
        order.append("state")
        state = {"season": "2026", "week": "7", "season_type": "off"}
        nfl_state.record_nfl_state(state)
        return state

    async def stop(name, fn, *a, **k):
        order.append(name)
        raise _StopScheduler

    nfl_state.reset_nfl_state()
    monkeypatch.setattr(scheduler, "fetch_nfl_state", fake_fetch)
    monkeypatch.setattr(scheduler, "run_job", stop)
    with pytest.raises(_StopScheduler):
        await scheduler.run_scheduler()
    assert order[:2] == ["state", "sync_players"]
    assert nfl_state.latest_season_type() == "off"


@pytest.mark.asyncio
async def test_scheduler_startup_survives_a_hung_or_failing_state_read(monkeypatch):
    monkeypatch.setattr(scheduler, "NFL_STATE_PRIME_TIMEOUT", 0.05)
    for behaviour in ("hang", "fail"):
        reached = []

        async def fake_fetch():
            if behaviour == "hang":
                await asyncio.sleep(10)
            raise httpx.ConnectError("sleeper down")

        async def stop(name, fn, *a, **k):
            reached.append(name)
            raise _StopScheduler

        monkeypatch.setattr(scheduler, "fetch_nfl_state", fake_fetch)
        monkeypatch.setattr(scheduler, "run_job", stop)
        with pytest.raises(_StopScheduler):
            await asyncio.wait_for(scheduler.run_scheduler(), 2)
        assert reached == ["sync_players"]
