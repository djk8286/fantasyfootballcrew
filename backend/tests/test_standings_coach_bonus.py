"""
Tests for coach-bonus scoring in calculate_week (Phase 2 Step 2,
"Front-Office finish-out"): the existing flat_weekly bonus (regression
coverage it never had before this phase), and the new win_bonus, which
required restructuring calculate_week into two passes -- base scores
first, then matchup winners determined from those base scores, then
win_bonus applied only to the actual winner. The seed fixture's 3 teams
(a, b, c) and MATCHUP_WEEK=3 convention are shared with
test_matchup_notifications.py (team_a vs team_b head-to-head, team_c
byes that week).

Every league in `seed` has an empty scoring_config and players with no
week_stats, so every player scores exactly 0 -- passing sleeper_stats={}
explicitly (not None) skips the real Sleeper network fetch entirely and
still resolves every stat lookup to {} either way. This means a team's
BASE score is driven entirely by its coach bonuses in these tests, which
is what makes forcing a specific winner (via a flat_weekly bonus on one
side) a clean, minimal way to set up a real win/loss differential without
needing to fabricate player stats.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.coach import Coach, CoachPosition
from app.models.weekly_score import WeeklyScore
from app.services.standings_service import calculate_week, get_standings

MATCHUP_WEEK = 3  # see test_matchup_notifications.py's own comment on this


async def _add_coach(db_session_factory, team_id, bonus_type, bonus_value, position=CoachPosition.HC):
    async with db_session_factory() as db:
        db.add(Coach(id=str(uuid.uuid4()), name="Test Coach", position=position,
                     team_id=team_id, bonus_type=bonus_type, bonus_value=bonus_value))
        await db.commit()


async def _score_for(db_session_factory, league_id, team_id, week, year=2026):
    async with db_session_factory() as db:
        result = await db.execute(
            select(WeeklyScore).where(
                WeeklyScore.league_id == league_id, WeeklyScore.team_id == team_id,
                WeeklyScore.week == week, WeeklyScore.year == year,
            )
        )
        return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_no_coach_baseline_regression(seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    assert score.total_score == 0.0
    assert "coach_bonus" not in score.lineup_data
    assert "win_bonus" not in score.lineup_data


@pytest.mark.asyncio
async def test_flat_weekly_bonus_applies_unconditionally(seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]
    await _add_coach(db_session_factory, team_a, "flat_weekly", 3.5)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    assert score.total_score == 3.5
    assert score.lineup_data["coach_bonus"] == 3.5


@pytest.mark.asyncio
async def test_win_bonus_applies_to_the_winner(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    # team_a's flat_weekly bonus is what makes it outscore team_b on base
    # total (both roster-score 0 otherwise) -- this is the win condition.
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)
    await _add_coach(db_session_factory, team_a, "win_bonus", 5.0, position=CoachPosition.OC)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    score_b = await _score_for(db_session_factory, league_id, team_b, MATCHUP_WEEK)
    assert score_a.total_score == 15.0  # 10.0 flat_weekly base + 5.0 win_bonus
    assert score_a.lineup_data["win_bonus"] == 5.0
    assert score_b.total_score == 0.0
    assert "win_bonus" not in score_b.lineup_data


@pytest.mark.asyncio
async def test_win_bonus_does_not_apply_to_the_loser(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)  # team_a wins on base score
    await _add_coach(db_session_factory, team_b, "win_bonus", 5.0)  # but team_b holds the win_bonus coach

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    score_b = await _score_for(db_session_factory, league_id, team_b, MATCHUP_WEEK)
    assert score_a.total_score == 10.0
    assert score_b.total_score == 0.0  # win_bonus never applied -- team_b lost
    assert "win_bonus" not in score_b.lineup_data


@pytest.mark.asyncio
async def test_win_bonus_does_not_apply_on_a_tie(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    # Equal base scores on both sides -- a tie.
    await _add_coach(db_session_factory, team_a, "win_bonus", 5.0)
    await _add_coach(db_session_factory, team_b, "win_bonus", 5.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    score_b = await _score_for(db_session_factory, league_id, team_b, MATCHUP_WEEK)
    assert score_a.total_score == 0.0
    assert score_b.total_score == 0.0


@pytest.mark.asyncio
async def test_win_bonus_does_not_error_on_a_bye_week(seed):
    league_id = seed["league_id"]
    team_c = seed["team_c"]  # byes at MATCHUP_WEEK, per the shared convention
    db_session_factory = seed["db_session_factory"]
    await _add_coach(db_session_factory, team_c, "win_bonus", 5.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_c = await _score_for(db_session_factory, league_id, team_c, MATCHUP_WEEK)
    assert score_c.total_score == 0.0
    assert "win_bonus" not in score_c.lineup_data


@pytest.mark.asyncio
async def test_get_standings_consistency_after_win_bonus(seed):
    """The one test that actually proves win_bonus can't corrupt
    get_standings' later win/loss recomputation, rather than just
    trusting the derivation in the code comment."""
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)
    await _add_coach(db_session_factory, team_a, "win_bonus", 5.0, position=CoachPosition.OC)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})
        standings = await get_standings(league_id, db)

    by_id = {s["team_id"]: s for s in standings}
    assert by_id[team_a]["wins"] == 1
    assert by_id[team_a]["losses"] == 0
    assert by_id[team_a]["points_for"] == 15.0
    assert by_id[team_b]["wins"] == 0
    assert by_id[team_b]["losses"] == 1
    assert by_id[team_b]["points_against"] == 15.0


@pytest.mark.asyncio
async def test_calculate_week_is_idempotent_with_win_bonus(seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)
    await _add_coach(db_session_factory, team_a, "win_bonus", 5.0, position=CoachPosition.OC)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    async with db_session_factory() as db:
        result = await db.execute(
            select(WeeklyScore).where(
                WeeklyScore.league_id == league_id, WeeklyScore.team_id == team_a,
                WeeklyScore.week == MATCHUP_WEEK, WeeklyScore.year == 2026,
            )
        )
        rows = result.scalars().all()
    assert len(rows) == 1  # upsert, not a duplicate row
    assert rows[0].total_score == 15.0  # not drifted/double-applied on the second run
