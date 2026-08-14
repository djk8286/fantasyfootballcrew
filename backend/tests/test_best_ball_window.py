"""
Pure unit tests for best_ball_service's window math (Phase 6 Step 2) --
is_window_open/describe_window. No DB, no client -- these are pure
functions of (now, settings), deliberately decoupled from the
scheduler's own _last_seen_week global (see best_ball_service.py's
module docstring for why that matters).

Anchor dates used below (all real 2026-08 calendar dates):
  Mon 2026-08-10, Tue 08-11, Wed 08-12, Thu 08-13,
  Fri 08-14, Sat 08-15, Sun 08-16, Wed 08-19 (next Wed after 08-13).
"""
from datetime import datetime

from app.services.best_ball_service import (
    DEFAULT_BEST_BALL_SETTINGS,
    is_window_open,
    describe_window,
)


def _settings(**overrides):
    merged = dict(DEFAULT_BEST_BALL_SETTINGS)
    merged.update(overrides)
    return merged


# --- Default window: closed Thursday 20:00 UTC -> Wednesday 10:00 UTC ---

def test_default_window_open_midday_wednesday():
    now = datetime(2026, 8, 12, 12, 0)  # Wednesday noon
    assert is_window_open(now, _settings()) is True


def test_default_window_closed_thursday_evening():
    now = datetime(2026, 8, 13, 21, 0)  # Thursday 21:00
    assert is_window_open(now, _settings()) is False


def test_default_window_closed_exactly_at_lock_moment():
    now = datetime(2026, 8, 13, 20, 0)  # Thursday 20:00 exactly
    assert is_window_open(now, _settings()) is False


def test_default_window_open_one_minute_before_lock():
    now = datetime(2026, 8, 13, 19, 59)  # Thursday 19:59
    assert is_window_open(now, _settings()) is True


def test_default_window_open_exactly_at_reopen_moment():
    now = datetime(2026, 8, 19, 10, 0)  # Wednesday 10:00 exactly
    assert is_window_open(now, _settings()) is True


def test_default_window_closed_one_minute_before_reopen():
    now = datetime(2026, 8, 19, 9, 59)  # Wednesday 09:59
    assert is_window_open(now, _settings()) is False


# --- Non-wrapping window (lock weekday < reopen weekday, same week) ---

def test_non_wrapping_window_closed_inside_span():
    # lock Tue 00:00, reopen Thu 00:00 -- closed Tue->Thu, open otherwise
    settings = _settings(lock_weekday=1, lock_hour=0, reopen_weekday=3, reopen_hour=0)
    now = datetime(2026, 8, 11, 12, 0)  # Tuesday noon, inside [Tue 00:00, Thu 00:00)
    assert is_window_open(now, settings) is False


def test_non_wrapping_window_open_outside_span():
    settings = _settings(lock_weekday=1, lock_hour=0, reopen_weekday=3, reopen_hour=0)
    now = datetime(2026, 8, 14, 12, 0)  # Friday noon, outside the span
    assert is_window_open(now, settings) is True


# --- describe_window ---

def test_describe_window_when_open_points_to_next_lock():
    settings = _settings()
    now = datetime(2026, 8, 12, 12, 0)  # Wednesday noon, open
    result = describe_window(now, settings)
    assert result["is_open"] is True
    assert result["next_transition_type"] == "closes"
    assert result["next_transition_at"] == datetime(2026, 8, 13, 20, 0)  # next Thursday 20:00


def test_describe_window_when_closed_points_to_next_reopen():
    settings = _settings()
    now = datetime(2026, 8, 13, 21, 0)  # Thursday 21:00, closed
    result = describe_window(now, settings)
    assert result["is_open"] is False
    assert result["next_transition_type"] == "opens"
    assert result["next_transition_at"] == datetime(2026, 8, 19, 10, 0)  # next Wednesday 10:00
