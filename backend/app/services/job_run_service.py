"""
Background-job run tracking (2026-10-17) -- the admin System Health panel's
data source. scheduler.py routes every job call through run_job(), which
times it and writes one JobRun row (success, or the exception text on
failure), then re-raises so each call site's existing try/except + print
keeps working exactly as before. Recording is best-effort: a failure to
write the JobRun row is printed and swallowed, never allowed to break the
job it was tracking.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.job_run import JobRun
from app.models.nfl_game import NFLGame
from app.models.draft import Draft, DraftRunStatus
from app.services.ai_cost_service import set_current_job, reset_current_job

JOB_RUN_RETENTION_DAYS = 7
MAX_ERROR_CHARS = 2000


@dataclass(frozen=True)
class JobSpec:
    label: str
    # A job whose last success is older than this is "stale". None = runs
    # on an event (e.g. the live NFL week changing), not a fixed cadence,
    # so it's never flagged stale -- only failed.
    stale_after_s: int | None


# Every job scheduler.py runs, keyed by the name passed to run_job. Stale
# thresholds are a few multiples of each job's real cadence (see the
# *_INTERVAL constants in scheduler.py) so one slow tick isn't an alert.
JOBS: dict[str, JobSpec] = {
    "sync_stats": JobSpec("Sleeper stats sync", 15 * 60),
    "calculate_scores": JobSpec("League auto-scoring", None),
    "sync_scoreboard": JobSpec("ESPN live scoreboard", None),
    "playoffs": JobSpec("Playoff processing", None),
    "best_ball_reopen": JobSpec("Best Ball window reopen", None),
    "guillotine": JobSpec("Guillotine eliminations", None),
    "matchup_notify": JobSpec("Matchup result notifications", None),
    "team_recaps": JobSpec("Weekly team recaps (AI)", None),
    "dashboard_summaries": JobSpec("Dashboard AI summaries check", 15 * 60),
    "team_news": JobSpec("Per-team player news check", 15 * 60),
    "sync_players": JobSpec("Sleeper player metadata sync", 3 * 60 * 60),
    "sync_projections": JobSpec("Sleeper projections sync", 3 * 60 * 60),
    "draft_timer": JobSpec("Draft timer watchdog", 5 * 60),
    "prune_job_runs": JobSpec("Job history pruning", 3 * 60 * 60),
}

# High-frequency jobs (draft_timer ticks every 5s) only persist a success
# row this often; failures are always recorded. Keyed by job name.
_last_success_recorded: dict[str, float] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes even for timezone=True columns.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _record(job_name: str, started_at: datetime, t0: float, success: bool, error: str | None) -> None:
    try:
        async with async_session() as db:
            db.add(JobRun(
                job_name=job_name,
                started_at=started_at,
                finished_at=_now(),
                duration_ms=int((time.monotonic() - t0) * 1000),
                success=success,
                error=error[:MAX_ERROR_CHARS] if error else None,
            ))
            await db.commit()
    except Exception as e:
        print(f"[job_runs] Failed to record run of {job_name}: {e}")


async def run_job(
    job_name: str,
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    record_success_every_s: float | None = None,
    **kwargs: Any,
) -> Any:
    """Run `fn(*args, **kwargs)`, record the outcome as a JobRun, and
    return its result (or re-raise its exception)."""
    started_at = _now()
    t0 = time.monotonic()
    # Lets AI calls made inside a background job be attributed to it in
    # ai_usage_events (endpoint "job:<name>") -- see ai_cost_service.
    job_token = set_current_job(job_name)
    try:
        result = await fn(*args, **kwargs)
    except Exception as e:
        await _record(job_name, started_at, t0, False, f"{type(e).__name__}: {e}")
        raise
    finally:
        reset_current_job(job_token)
    if record_success_every_s is not None:
        last = _last_success_recorded.get(job_name)
        if last is not None and t0 - last < record_success_every_s:
            return result
        _last_success_recorded[job_name] = t0
    await _record(job_name, started_at, t0, True, None)
    return result


async def prune_job_runs(retention_days: int = JOB_RUN_RETENTION_DAYS) -> int:
    cutoff = _now() - timedelta(days=retention_days)
    async with async_session() as db:
        result = await db.execute(delete(JobRun).where(JobRun.started_at < cutoff))
        await db.commit()
        return result.rowcount or 0


def _job_status(spec: JobSpec | None, last_run: JobRun | None, last_success_at: datetime | None, now: datetime) -> str:
    if last_run is None:
        return "never_run"
    if not last_run.success:
        return "failed"
    if spec and spec.stale_after_s is not None and last_success_at is not None:
        if (now - last_success_at).total_seconds() > spec.stale_after_s:
            return "stale"
    return "ok"


async def get_system_health(db: AsyncSession) -> dict:
    now = _now()
    since_24h = now - timedelta(hours=24)

    # Latest row per job (any outcome), via max(started_at) per job_name.
    latest_sub = (
        select(JobRun.job_name, func.max(JobRun.started_at).label("max_started"))
        .group_by(JobRun.job_name)
        .subquery()
    )
    latest_rows = (await db.execute(
        select(JobRun).join(
            latest_sub,
            (JobRun.job_name == latest_sub.c.job_name) & (JobRun.started_at == latest_sub.c.max_started),
        )
    )).scalars().all()
    latest = {r.job_name: r for r in latest_rows}

    last_success = dict((await db.execute(
        select(JobRun.job_name, func.max(JobRun.finished_at)).where(JobRun.success.is_(True)).group_by(JobRun.job_name)
    )).all())

    failure_sub = (
        select(JobRun.job_name, func.max(JobRun.started_at).label("max_started"))
        .where(JobRun.success.is_(False))
        .group_by(JobRun.job_name)
        .subquery()
    )
    failure_rows = (await db.execute(
        select(JobRun).join(
            failure_sub,
            (JobRun.job_name == failure_sub.c.job_name) & (JobRun.started_at == failure_sub.c.max_started),
        )
    )).scalars().all()
    last_failure = {r.job_name: r for r in failure_rows}

    counts_24h: dict[str, dict[str, int]] = {}
    for name, success, n in (await db.execute(
        select(JobRun.job_name, JobRun.success, func.count(JobRun.id))
        .where(JobRun.started_at >= since_24h)
        .group_by(JobRun.job_name, JobRun.success)
    )).all():
        c = counts_24h.setdefault(name, {"runs": 0, "failures": 0})
        c["runs"] += n
        if not success:
            c["failures"] += n

    jobs = []
    for name in list(JOBS) + sorted(set(latest) - set(JOBS)):
        spec = JOBS.get(name)
        run = latest.get(name)
        success_at = _aware(last_success.get(name))
        failure = last_failure.get(name)
        jobs.append({
            "name": name,
            "label": spec.label if spec else name,
            "status": _job_status(spec, run, success_at, now),
            "stale_after_seconds": spec.stale_after_s if spec else None,
            "last_run_at": _aware(run.started_at).isoformat() if run else None,
            "last_duration_ms": run.duration_ms if run else None,
            "last_success_at": success_at.isoformat() if success_at else None,
            "last_failure_at": _aware(failure.started_at).isoformat() if failure else None,
            "last_error": failure.error if failure else None,
            "runs_24h": counts_24h.get(name, {}).get("runs", 0),
            "failures_24h": counts_24h.get(name, {}).get("failures", 0),
        })

    # Data freshness. Player has no updated_at of its own, so its
    # freshness IS the last successful player sync.
    latest_game_sync = _aware((await db.execute(select(func.max(NFLGame.synced_at)))).scalar())
    players_synced = _aware(last_success.get("sync_players"))
    stats_synced = _aware(last_success.get("sync_stats"))

    def _fresh(at: datetime | None) -> dict:
        return {
            "updated_at": at.isoformat() if at else None,
            "age_seconds": int((now - at).total_seconds()) if at else None,
        }

    # Draft timer health: the watchdog's own last tick, plus any timed
    # in-progress draft whose current pick is well past its deadline
    # (the watchdog should have auto-picked within seconds).
    timed = (await db.execute(
        select(Draft).where(
            Draft.status == DraftRunStatus.IN_PROGRESS,
            Draft.timer_seconds > 0,
            Draft.current_pick_started_at.isnot(None),
        )
    )).scalars().all()
    overdue = []
    for d in timed:
        deadline = _aware(d.current_pick_started_at) + timedelta(seconds=d.timer_seconds)
        late = (now - deadline).total_seconds()
        if late > 60:
            overdue.append({"draft_id": d.id, "league_id": d.league_id, "seconds_overdue": int(late)})
    in_progress = (await db.execute(
        select(func.count(Draft.id)).where(Draft.status == DraftRunStatus.IN_PROGRESS)
    )).scalar() or 0
    timer_job = next(j for j in jobs if j["name"] == "draft_timer")

    return {
        "generated_at": now.isoformat(),
        "jobs": jobs,
        "freshness": {
            "espn_games": _fresh(latest_game_sync),
            "sleeper_players": _fresh(players_synced),
            "sleeper_stats": _fresh(stats_synced),
        },
        "draft_timer": {
            "status": timer_job["status"],
            "last_tick_at": timer_job["last_success_at"],
            "in_progress_drafts": in_progress,
            "timed_drafts": len(timed),
            "overdue_drafts": overdue,
        },
    }
