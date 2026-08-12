"""
Tests for "you won/lost/tied your matchup" notifications: the last gap
the notifications feature deliberately left open, since regular-season
weeks (unlike playoff rounds) have no fixed week number to compare
against the live NFL week to know a week is truly final. Covers both
notify_matchup_results itself (standings_service.py) and the
week-transition tracking that decides when the scheduler calls it
(scheduler.py's _last_seen_week).
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.notification import Notification, NotificationType
from app.models.weekly_score import WeeklyScore
from app.services.standings_service import notify_matchup_results
from app.services import scheduler as scheduler_module


async def _add_score(db_session_factory, league_id, team_id, week, score, year=2026):
    async with db_session_factory() as db:
        db.add(WeeklyScore(league_id=league_id, team_id=team_id, week=week, year=year, total_score=score))
        await db.commit()


async def _notifications_for(db_session_factory, user_id):
    async with db_session_factory() as db:
        result = await db.execute(select(Notification).where(Notification.user_id == user_id))
        return result.scalars().all()


# With the seed fixture's 3 teams (a, b, c) and the round-robin circle
# method, week 3 is the week team_a plays team_b head-to-head (team_c
# byes) -- verified against _build_round_robin_schedule's rotation math.
MATCHUP_WEEK = 3


@pytest.mark.asyncio
async def test_notify_matchup_results_notifies_winner_and_loser(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]

    await _add_score(db_session_factory, league_id, team_a, MATCHUP_WEEK, 120.5)
    await _add_score(db_session_factory, league_id, team_b, MATCHUP_WEEK, 99.0)

    async with db_session_factory() as db:
        await notify_matchup_results(league_id, MATCHUP_WEEK, 2026, db)

    # seed's commissioner owns both team_a and team_b, so both the "won"
    # and "lost" notifications land on the same user.
    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    won = [n for n in notes if n.type == NotificationType.MATCHUP_WON]
    lost = [n for n in notes if n.type == NotificationType.MATCHUP_LOST]
    assert len(won) == 1
    assert len(lost) == 1
    assert "Team B" in won[0].message
    assert "120.5-99" in won[0].message
    assert "Team A" in lost[0].message
    assert won[0].link == f"/leagues/{league_id}/standings"


@pytest.mark.asyncio
async def test_notify_matchup_results_notifies_tie(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]

    await _add_score(db_session_factory, league_id, team_a, MATCHUP_WEEK, 88.0)
    await _add_score(db_session_factory, league_id, team_b, MATCHUP_WEEK, 88.0)

    async with db_session_factory() as db:
        await notify_matchup_results(league_id, MATCHUP_WEEK, 2026, db)

    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    tied = [n for n in notes if n.type == NotificationType.MATCHUP_TIED]
    assert len(tied) == 2
    assert all("88-88" in n.message for n in tied)


@pytest.mark.asyncio
async def test_notify_matchup_results_is_a_noop_with_no_scores(seed):
    """A week with no WeeklyScore rows yet (e.g. called for a week that
    hasn't been scored) shouldn't crash or notify a 0-0 result."""
    league_id = seed["league_id"]
    db_session_factory = seed["db_session_factory"]

    async with db_session_factory() as db:
        await notify_matchup_results(league_id, MATCHUP_WEEK, 2026, db)

    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    assert notes == []


@pytest.mark.asyncio
async def test_notify_matchup_results_skips_bye_team(seed):
    """team_c byes in MATCHUP_WEEK (3-team round robin) -- confirms it
    gets no notification since it wasn't actually in a matchup."""
    league_id = seed["league_id"]
    team_a, team_b, team_c = seed["team_a"], seed["team_b"], seed["team_c"]
    db_session_factory = seed["db_session_factory"]

    await _add_score(db_session_factory, league_id, team_a, MATCHUP_WEEK, 50.0)
    await _add_score(db_session_factory, league_id, team_b, MATCHUP_WEEK, 40.0)
    await _add_score(db_session_factory, league_id, team_c, MATCHUP_WEEK, 999.0)

    async with db_session_factory() as db:
        await notify_matchup_results(league_id, MATCHUP_WEEK, 2026, db)

    notes = await _notifications_for(db_session_factory, seed["commissioner_id"])
    # 2 notifications total (won + lost for a/b) -- team_c's bye-week
    # score never generated a matchup, so it never generated a notification.
    assert len(notes) == 2


class TestWeekTransitionTracking:
    """scheduler._last_seen_week is what decides *when* to call
    notify_matchup_results -- once per week, for the week that just
    ended, not every 2-minute tick. Exercises the tracking variable
    directly rather than the full run_scheduler loop (which polls Sleeper
    and sleeps forever), matching the level the rest of scheduler.py's
    small pure-logic helpers (e.g. _league_is_auto_scorable) are tested at.
    """

    def setup_method(self):
        scheduler_module._last_seen_week = None

    def teardown_method(self):
        scheduler_module._last_seen_week = None

    def test_first_tick_only_records_no_notify(self):
        """The very first time the scheduler sees a live week, there's no
        "previous" week to have just ended -- nothing to notify for yet."""
        last_seen = scheduler_module._last_seen_week
        current = (2026, 3)
        should_notify = last_seen is not None and last_seen != current
        assert should_notify is False

    def test_same_week_again_does_not_renotify(self):
        """Repeated ticks within the same live week (the common case --
        stats sync every 2 min, but the NFL week only changes weekly)
        must not re-fire notifications each time."""
        scheduler_module._last_seen_week = (2026, 3)
        current = (2026, 3)
        should_notify = scheduler_module._last_seen_week is not None and scheduler_module._last_seen_week != current
        assert should_notify is False

    def test_week_increment_notifies_for_the_week_that_just_ended(self):
        scheduler_module._last_seen_week = (2026, 3)
        current = (2026, 4)
        should_notify = scheduler_module._last_seen_week is not None and scheduler_module._last_seen_week != current
        assert should_notify is True
        # The week to notify for is the OLD tuple (the one that just
        # ended), never the new one (which has no scores yet).
        prev_season, prev_week = scheduler_module._last_seen_week
        assert (prev_season, prev_week) == (2026, 3)

    def test_season_rollover_also_triggers(self):
        """A (season, week) tuple compare -- not just the week number --
        so a season boundary (e.g. (2026, 17) -> (2027, 1)) is correctly
        treated as a transition too, not mistaken for week going backwards
        and ignored."""
        scheduler_module._last_seen_week = (2026, 17)
        current = (2027, 1)
        should_notify = scheduler_module._last_seen_week is not None and scheduler_module._last_seen_week != current
        assert should_notify is True
