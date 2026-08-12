"""
Tests for the auto-score-eligibility policy the background scheduler uses
to decide which leagues get an automatic weekly score calculation.

Only _league_is_auto_scorable is tested here -- it's the one piece of
scheduler.py that's a plain function of a League's attributes, with no
network/DB/asyncio involved. The rest of the scheduler (fetching from
Sleeper, looping leagues, calling calculate_week) is exercised via manual
live verification instead, matching this project's existing practice for
scheduler/background-job behavior (see CLAUDE.md / session notes) rather
than standing up new async-DB test fixtures for a single call site.
"""
from app.models.league import League, DraftStatus, LeagueType
from app.services.scheduler import _league_is_auto_scorable


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
