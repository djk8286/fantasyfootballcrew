"""
Tests for the auto-score-eligibility policy the background scheduler uses
to decide which leagues get an automatic weekly score calculation, plus
the daily-refresh staleness check the Dashboard AI Summaries / Team
Player News scheduler passes both use (2026-09-22).

Only plain functions of in-memory values are tested here -- no network/
DB/asyncio involved. The rest of the scheduler (fetching from Sleeper,
looping leagues, calling calculate_week) is exercised via manual live
verification instead, matching this project's existing practice for
scheduler/background-job behavior (see CLAUDE.md / session notes) rather
than standing up new async-DB test fixtures for a single call site.
"""
from datetime import datetime, timedelta, timezone
from app.models.league import League, DraftStatus, LeagueType
from app.services.scheduler import _league_is_auto_scorable, _is_fresh, DASHBOARD_SUMMARY_REFRESH_INTERVAL


def _league(is_mock: bool, draft_status: DraftStatus) -> League:
    # League() doesn't touch the DB -- this just sets attributes on a plain
    # Python object, which is all _league_is_auto_scorable reads.
    return League(
        name="Test League",
        commissioner_id="user-1",
        is_mock=is_mock,
        draft_status=draft_status,
        league_type=LeagueType.STANDARD,
    )


def test_real_completed_league_is_scorable():
    assert _league_is_auto_scorable(_league(is_mock=False, draft_status=DraftStatus.COMPLETED)) is True


def test_mock_league_is_never_scorable_even_if_draft_completed():
    assert _league_is_auto_scorable(_league(is_mock=True, draft_status=DraftStatus.COMPLETED)) is False


def test_real_league_not_scorable_before_draft_completes():
    assert _league_is_auto_scorable(_league(is_mock=False, draft_status=DraftStatus.NOT_STARTED)) is False
    assert _league_is_auto_scorable(_league(is_mock=False, draft_status=DraftStatus.IN_PROGRESS)) is False


def test_mock_league_mid_draft_is_not_scorable():
    assert _league_is_auto_scorable(_league(is_mock=True, draft_status=DraftStatus.IN_PROGRESS)) is False


# ─── _is_fresh: the daily-refresh staleness check ────────────────────────
#
# Regression coverage for the actual reported bug (dashboard showing
# "wrong weeks and scores"): the OLD trigger was in-memory and
# transition-edge-triggered, so a redeploy (this project does that
# often) could silently drop the one moment it would have fired,
# leaving these panels stale indefinitely. The fix is durable (DB-
# backed via each row's updated_at) and wall-clock-based -- these tests
# pin exactly the boundary behavior that makes it durable.

def test_a_row_updated_moments_ago_is_fresh():
    now = datetime.now(timezone.utc)
    assert _is_fresh(now - timedelta(minutes=1), now) is True


def test_a_row_updated_25_hours_ago_is_stale():
    now = datetime.now(timezone.utc)
    assert _is_fresh(now - timedelta(hours=25), now) is False


def test_exactly_at_the_interval_boundary_is_stale():
    now = datetime.now(timezone.utc)
    assert _is_fresh(now - DASHBOARD_SUMMARY_REFRESH_INTERVAL, now) is False


def test_naive_datetime_from_sqlite_is_treated_as_utc_not_local():
    """SQLite drops tzinfo on round-trip even though the column is
    declared DateTime(timezone=True) -- a naive value read back from
    the DB must still be compared correctly, not silently misread as
    local time (which could make a genuinely-fresh row look stale, or
    vice versa, depending on the server's local timezone)."""
    now = datetime.now(timezone.utc)
    naive_recent = (now - timedelta(minutes=5)).replace(tzinfo=None)
    assert _is_fresh(naive_recent, now) is True

    naive_stale = (now - timedelta(hours=25)).replace(tzinfo=None)
    assert _is_fresh(naive_stale, now) is False
