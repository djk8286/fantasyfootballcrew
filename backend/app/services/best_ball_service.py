"""
Best-Ball Hybrid (Phase 6).

Bolts an always-on-optimal-lineup mode onto the existing, unmodified
scoring pipeline. Entirely opt-in per league
(League.best_ball_settings["enabled"], default False). Two independent
pieces:

1. Scoring: calculate_week (standings_service.py) calls the existing,
   already-tested calculate_optimal_lineup (scoring_engine.py) directly,
   using that week's real per-player stats it already has in hand --
   NOT the /lineup/optimize endpoint, which uses season-aggregate stats
   and would be wrong for genuine best-ball semantics. The result is
   never persisted as a Lineup row; it's recomputed fresh every call, so
   a best-ball lineup naturally stays live through an in-progress week
   and becomes final the moment the week itself does.

2. Management Window: a weekly recurring lock/reopen span (UTC,
   deliberately NOT tied to the scheduler's _last_seen_week -- that
   global resets to None on every redeploy, which is an acceptable
   lossy tradeoff for a notification but NOT for a correctness-
   sensitive gate on trade/waiver actions) that gates trade approvals
   and waiver-claim processing. Trade/waiver *creation* stays completely
   open regardless of window state -- only the granting action is gated.
   is_window_open is pure wall-clock math, trivially unit-testable at
   exact boundaries.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.models.league import League

DEFAULT_BEST_BALL_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "lock_weekday": 3,   # Thursday 20:00 UTC -- approximates a TNF-style lock
    "lock_hour": 20,
    "reopen_weekday": 2,  # Wednesday 10:00 UTC -- classic "waivers clear Wednesday"
    "reopen_hour": 10,
}


def get_best_ball_settings(league: League) -> dict[str, Any]:
    merged = dict(DEFAULT_BEST_BALL_SETTINGS)
    merged.update(league.best_ball_settings or {})
    return merged


def is_window_open(now: datetime, settings: dict) -> bool:
    """Pure time math -- ignores settings["enabled"]; callers check that
    first. True unless `now` (UTC) falls in the weekly closed span
    [lock, reopen), wrapping across the week boundary when lock > reopen
    (the default: closed Thu->Wed)."""
    lock = settings["lock_weekday"] * 1440 + settings["lock_hour"] * 60
    reopen = settings["reopen_weekday"] * 1440 + settings["reopen_hour"] * 60
    now_m = now.weekday() * 1440 + now.hour * 60 + now.minute
    if lock <= reopen:
        closed = lock <= now_m < reopen
    else:
        closed = now_m >= lock or now_m < reopen
    return not closed


def _next_occurrence(now: datetime, weekday: int, hour: int) -> datetime:
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    candidate += timedelta(days=(weekday - now.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def describe_window(now: datetime, settings: dict) -> dict:
    """For GET .../management-window -- is_open plus the next
    transition, so the frontend can render a countdown without its own
    clock math."""
    open_now = is_window_open(now, settings)
    if open_now:
        next_at = _next_occurrence(now, settings["lock_weekday"], settings["lock_hour"])
        next_type = "closes"
    else:
        next_at = _next_occurrence(now, settings["reopen_weekday"], settings["reopen_hour"])
        next_type = "opens"
    return {
        "is_open": open_now,
        "next_transition_at": next_at,
        "next_transition_type": next_type,
    }
