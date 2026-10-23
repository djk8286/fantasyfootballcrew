"""
Real live "what NFL week is it" -- 2026-09-10. Before this, every page that
needed "the current week" (league page's live-score panel, Schedule's
default week, Standings' default week) each had its own frontend heuristic
guessing from whatever data happened to be loaded (e.g. "the first week
with a projected-not-final matchup") -- fragile, and each one could
disagree with the others. Sleeper's own /state/nfl is the one real,
authoritative source the scheduler already uses for this exact purpose
(see app/services/scheduler.py's fetch_nfl_state/_sync_stats_once) --
notably, it does NOT advance to the next week until Sleeper considers the
previous week's games actually over (confirmed: week 1 starting on a
Wednesday-night opener doesn't roll to week 2 until after the following
Monday night game), which is exactly the "we know what week we're in"
behavior a calendar-date heuristic could never get right on its own.
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.job_run_service import get_sync_status
from app.core.limiter import limiter
from app.services.nfl_state import MAX_AGE_S, latest_season_type, normalize_season_type
from app.services.scheduler import fetch_nfl_state

router = APIRouter(prefix="/nfl", tags=["nfl"])

# Short in-memory cache -- every page load that needs "the current week"
# would otherwise be a fresh network call to Sleeper's API; a 60s cache
# is far more current than any real use needs (this doesn't drive
# scoring itself, just which week a page defaults to showing) while
# keeping this endpoint cheap to hit from anywhere.
_state_cache: dict | None = None
_state_cache_at: float = 0.0
STATE_CACHE_TTL = 60.0


@router.get("/current-week")
async def get_current_week():
    """{season, week, season_type} -- the live NFL week, straight from
    Sleeper, cached briefly. season_type is one of "pre"/"regular"/"post"."""
    return await current_nfl_week()


async def current_nfl_week() -> dict:
    """The cached state behind GET /nfl/current-week, for server-side
    callers that must agree with it (the dashboard panels)."""
    global _state_cache, _state_cache_at
    now = time.monotonic()
    if _state_cache is None or (now - _state_cache_at) > STATE_CACHE_TTL:
        state = await fetch_nfl_state()
        _state_cache = {
            "season": int(state["season"]),
            "week": int(state["week"]),
            "season_type": state.get("season_type"),
        }
        _state_cache_at = now
    return _state_cache


class SourceStatus(BaseModel):
    last_success_at: Optional[str] = None
    last_attempt_at: Optional[str] = None
    last_attempt_ok: Optional[bool] = None


class SyncStatus(BaseModel):
    generated_at: str
    # Sleeper's season_type ("pre" | "regular" | "post" | "off"), or None
    # when the scheduler hasn't read a known value in the last 30 minutes.
    # The syncs only pull stats in the regular season, so the chip hides
    # itself outside it.
    season_type: Optional[str] = None
    sources: Dict[str, SourceStatus]


SYNC_STATUS_TTL = 30.0  # seconds; the chip polls every 60s per open tab
SYNC_STATUS_DB_TIMEOUT = 5.0  # seconds; past this, serve the old copy or 503
# Only the job_runs read is cached. generated_at is stamped per response,
# so the chip's clock-skew math never sees a 30s-old server time, and
# season_type is read from memory per response.
_sync_cache: dict | None = None  # {source: SourceStatus dict}
_sync_cache_at: float = 0.0
# When the last refill failed. Requests that queued behind it fail fast
# instead of each waiting out its own timeout on a stuck database.
_sync_failed_at: float | None = None
_sync_lock = asyncio.Lock()


def reset_sync_status_cache() -> None:
    global _sync_cache, _sync_cache_at, _sync_failed_at, _sync_lock
    _sync_cache, _sync_cache_at, _sync_failed_at = None, 0.0, None
    _sync_lock = asyncio.Lock()


def _sync_fresh(now: float) -> bool:
    return _sync_cache is not None and now - _sync_cache_at <= SYNC_STATUS_TTL


async def _cached_sources(db: AsyncSession) -> dict:
    global _sync_cache, _sync_cache_at, _sync_failed_at
    if _sync_fresh(time.monotonic()):
        return _sync_cache
    # Someone is already refilling. Serve the old copy rather than queue.
    if _sync_lock.locked() and _sync_cache is not None:
        return _sync_cache
    waited_from = time.monotonic()
    async with _sync_lock:
        if _sync_fresh(time.monotonic()):
            return _sync_cache
        if _sync_failed_at is not None and _sync_failed_at >= waited_from:
            # The refill this request waited on just failed.
            if _sync_cache is not None:
                return _sync_cache
            raise HTTPException(status_code=503, detail="Sync status is unavailable right now")
        try:
            result = await asyncio.wait_for(get_sync_status(db), SYNC_STATUS_DB_TIMEOUT)
        except Exception as e:  # includes asyncio.TimeoutError
            _sync_failed_at = time.monotonic()
            print(f"[sync-status] job_runs read failed ({type(e).__name__}); "
                  f"{'serving the cached copy' if _sync_cache is not None else 'returning 503'}")
            if _sync_cache is not None:
                return _sync_cache
            raise HTTPException(status_code=503, detail="Sync status is unavailable right now")
        _sync_cache, _sync_cache_at, _sync_failed_at = result["sources"], time.monotonic(), None
        return _sync_cache


def _season_type() -> Optional[str]:
    """What the scheduler last saw, else the /current-week cache if it's
    recent. Both come from Sleeper's /state/nfl."""
    st = latest_season_type()
    if st is not None:
        return st
    if _state_cache is not None and time.monotonic() - _state_cache_at <= MAX_AGE_S:
        return normalize_season_type(_state_cache.get("season_type"))
    return None


@router.get("/sync-status", response_model=SyncStatus)
@limiter.limit("120/minute")
async def sync_status(request: Request, db: AsyncSession = Depends(get_db)):
    """When the Sleeper stats and ESPN scoreboard syncs last succeeded,
    for the freshness chip. Site-wide, no league data, and no outbound
    call: season_type is whatever the scheduler last saw from Sleeper."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season_type": _season_type(),
        "sources": await _cached_sources(db),
    }
