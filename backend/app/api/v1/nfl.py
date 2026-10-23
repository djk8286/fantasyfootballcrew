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
import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.job_run_service import get_sync_status
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


@router.get("/sync-status")
async def sync_status(db: AsyncSession = Depends(get_db)):
    """When the Sleeper stats and ESPN scoreboard syncs last succeeded,
    for the freshness chip. Site-wide, no league data."""
    return await get_sync_status(db)
