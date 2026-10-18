"""
Tests for background-job run tracking (job_run_service) and the admin
System Health endpoint built on it.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from app.models.job_run import JobRun
from app.models.nfl_game import NFLGame
from app.models.draft import Draft, DraftRunStatus
from app.models.league import League, LeagueType
from app.services import job_run_service
from tests.test_admin import _make_user


@pytest.fixture
def tracked_session(db_session_factory, monkeypatch):
    """Point run_job/prune_job_runs at the per-test DB."""
    monkeypatch.setattr(job_run_service, "async_session", db_session_factory)
    job_run_service._last_success_recorded.clear()
    return db_session_factory


async def _runs(factory, name=None):
    async with factory() as db:
        q = select(JobRun)
        if name:
            q = q.where(JobRun.job_name == name)
        return (await db.execute(q.order_by(JobRun.started_at))).scalars().all()


@pytest.mark.asyncio
async def test_run_job_records_success_and_returns_result(tracked_session):
    async def job(x):
        return x * 2

    assert await job_run_service.run_job("sync_stats", job, 21) == 42
    rows = await _runs(tracked_session)
    assert len(rows) == 1
    assert rows[0].job_name == "sync_stats" and rows[0].success and rows[0].error is None
    assert rows[0].duration_ms >= 0


@pytest.mark.asyncio
async def test_run_job_records_failure_and_reraises(tracked_session):
    async def job():
        raise RuntimeError("sleeper is down")

    with pytest.raises(RuntimeError):
        await job_run_service.run_job("sync_stats", job)
    rows = await _runs(tracked_session)
    assert len(rows) == 1 and not rows[0].success
    assert rows[0].error == "RuntimeError: sleeper is down"


@pytest.mark.asyncio
async def test_run_job_throttles_success_rows_but_never_failures(tracked_session):
    async def ok():
        return None

    async def bad():
        raise ValueError("boom")

    for _ in range(5):
        await job_run_service.run_job("draft_timer", ok, record_success_every_s=60)
    for _ in range(2):
        with pytest.raises(ValueError):
            await job_run_service.run_job("draft_timer", bad, record_success_every_s=60)
    rows = await _runs(tracked_session, "draft_timer")
    assert [r.success for r in rows] == [True, False, False]


@pytest.mark.asyncio
async def test_recording_failure_never_breaks_the_job(monkeypatch):
    def broken_session():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(job_run_service, "async_session", broken_session)

    async def job():
        return "done"

    assert await job_run_service.run_job("sync_stats", job) == "done"


@pytest.mark.asyncio
async def test_prune_deletes_only_old_rows(tracked_session):
    now = datetime.now(timezone.utc)
    async with tracked_session() as db:
        for days in (1, 6, 8, 30):
            t = now - timedelta(days=days)
            db.add(JobRun(job_name="sync_stats", started_at=t, finished_at=t, duration_ms=1, success=True))
        await db.commit()
    assert await job_run_service.prune_job_runs() == 2
    assert len(await _runs(tracked_session)) == 2


@pytest.mark.asyncio
async def test_system_health_requires_admin(client, db_session_factory):
    _user, token = await _make_user(db_session_factory, is_admin=False)
    client.headers["Authorization"] = f"Bearer {token}"
    assert (await client.get("/admin/system-health")).status_code == 403


@pytest.mark.asyncio
async def test_system_health_reports_status_freshness_and_draft_timer(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    now = datetime.now(timezone.utc)

    def run(name, minutes_ago, success=True, error=None):
        t = now - timedelta(minutes=minutes_ago)
        return JobRun(job_name=name, started_at=t, finished_at=t, duration_ms=12, success=success, error=error)

    async with db_session_factory() as db:
        db.add_all([
            run("sync_stats", 3),                                   # ok
            run("sync_players", 600),                               # stale (> 3h)
            run("sync_scoreboard", 30),
            run("sync_scoreboard", 2, success=False, error="HTTPError: 503"),  # failed (latest)
            run("draft_timer", 1),
        ])
        league = League(id=str(uuid.uuid4()), name="L", commissioner_id=admin.id,
                        league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        db.add(Draft(league_id=league.id, status=DraftRunStatus.IN_PROGRESS, timer_seconds=60,
                     current_pick_started_at=now - timedelta(minutes=10)))
        db.add(NFLGame(espn_event_id="401", year=2026, week=6, season_type=2,
                       home_team="KC", home_team_name="Kansas City Chiefs",
                       away_team="BUF", away_team_name="Buffalo Bills",
                       status_state="in", status_detail="Q3", kickoff_at=now))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/system-health")
    assert r.status_code == 200
    data = r.json()
    jobs = {j["name"]: j for j in data["jobs"]}
    assert jobs["sync_stats"]["status"] == "ok"
    assert jobs["sync_players"]["status"] == "stale"
    assert jobs["sync_scoreboard"]["status"] == "failed"
    assert jobs["sync_scoreboard"]["last_error"] == "HTTPError: 503"
    assert jobs["sync_scoreboard"]["last_success_at"] is not None
    assert jobs["sync_scoreboard"]["runs_24h"] == 2 and jobs["sync_scoreboard"]["failures_24h"] == 1
    assert jobs["team_news"]["status"] == "never_run"

    assert data["freshness"]["espn_games"]["updated_at"] is not None
    assert data["freshness"]["sleeper_players"]["age_seconds"] >= 600 * 60 - 5

    dt = data["draft_timer"]
    assert dt["status"] == "ok" and dt["in_progress_drafts"] == 1 and dt["timed_drafts"] == 1
    assert len(dt["overdue_drafts"]) == 1 and dt["overdue_drafts"][0]["seconds_overdue"] >= 500
