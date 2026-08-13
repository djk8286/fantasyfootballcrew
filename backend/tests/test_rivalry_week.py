"""
Tests for the Rivalry Week bonus in calculate_week (Phase 3 Step 4,
"Enhanced Conference/Rivalry") -- a flat, league-wide bonus (not a Coach
bonus) added to every team that wins its matchup during a commissioner-
designated week, only for CONFERENCE leagues. Reuses the same
base-scores-then-winners two-pass structure Phase 2's win_bonus already
established in calculate_week.

Uses the seed fixture's 3-team league and the MATCHUP_WEEK=3 convention
shared with test_matchup_notifications.py/test_standings_coach_bonus.py
(team_a vs team_b head-to-head, team_c byes that week). seed's league
defaults to LeagueType.STANDARD, so tests that need the rivalry gate to
actually be reachable flip it to CONFERENCE via direct DB mutation --
Team.conference itself is never set (stays None for all three teams),
which is fine: _build_league_schedule groups by Team.conference, and
None == None for all three teams still collapses to one group, matching
the existing MATCHUP_WEEK=3 convention exactly. The rivalry gate only
checks League.league_type, not Team.conference, so this is valid without
needing to assign "A"/"B" to any team.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.coach import Coach, CoachPosition
from app.models.league import League, LeagueType
from app.models.weekly_score import WeeklyScore
from app.services.standings_service import calculate_week, get_standings

MATCHUP_WEEK = 3


async def _make_conference(db_session_factory, league_id):
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.league_type = LeagueType.CONFERENCE
        await db.commit()


async def _set_rivalry_settings(db_session_factory, league_id, enabled, week, bonus_value):
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.rivalry_week_settings = {"enabled": enabled, "week": week, "bonus_value": bonus_value}
        await db.commit()


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
async def test_rivalry_bonus_applies_to_winner_on_rivalry_week(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK, 7.0)
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)  # forces team_a to win on base score

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    assert score_a.total_score == 17.0  # 10.0 base + 7.0 rivalry
    assert score_a.lineup_data["rivalry_bonus"] == 7.0


@pytest.mark.asyncio
async def test_rivalry_bonus_does_not_apply_to_loser(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK, 7.0)
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_b = await _score_for(db_session_factory, league_id, team_b, MATCHUP_WEEK)
    assert score_b.total_score == 0.0
    assert "rivalry_bonus" not in score_b.lineup_data


@pytest.mark.asyncio
async def test_rivalry_bonus_does_not_apply_on_non_rivalry_week(seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK + 1, 7.0)  # different week
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    assert score_a.total_score == 10.0
    assert "rivalry_bonus" not in score_a.lineup_data


@pytest.mark.asyncio
async def test_rivalry_bonus_does_not_apply_when_disabled(seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, False, MATCHUP_WEEK, 7.0)
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    assert score_a.total_score == 10.0
    assert "rivalry_bonus" not in score_a.lineup_data


@pytest.mark.asyncio
async def test_rivalry_bonus_does_not_apply_to_non_conference_league(seed):
    """Proves the league_type gate independent of enabled/week -- the
    league stays STANDARD (no _make_conference call)."""
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK, 7.0)
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    assert score_a.total_score == 10.0
    assert "rivalry_bonus" not in score_a.lineup_data


@pytest.mark.asyncio
async def test_rivalry_bonus_coexists_with_win_bonus(seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK, 7.0)
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)
    await _add_coach(db_session_factory, team_a, "win_bonus", 5.0, position=CoachPosition.OC)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    assert score_a.total_score == 22.0  # 10.0 base + 5.0 win_bonus + 7.0 rivalry
    assert score_a.lineup_data["win_bonus"] == 5.0
    assert score_a.lineup_data["rivalry_bonus"] == 7.0


@pytest.mark.asyncio
async def test_rivalry_bonus_does_not_apply_on_a_tie(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK, 7.0)
    # Both teams start at 0.0 base -- a tie, nobody wins.

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK)
    score_b = await _score_for(db_session_factory, league_id, team_b, MATCHUP_WEEK)
    assert "rivalry_bonus" not in score_a.lineup_data
    assert "rivalry_bonus" not in score_b.lineup_data


@pytest.mark.asyncio
async def test_get_standings_consistency_after_rivalry_bonus(seed):
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK, 7.0)
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})
        standings = await get_standings(league_id, db)

    by_id = {s["team_id"]: s for s in standings}
    assert by_id[team_a]["wins"] == 1
    assert by_id[team_a]["losses"] == 0
    assert by_id[team_a]["points_for"] == 17.0
    assert by_id[team_b]["wins"] == 0
    assert by_id[team_b]["losses"] == 1
    assert by_id[team_b]["points_against"] == 17.0


@pytest.mark.asyncio
async def test_calculate_week_is_idempotent_with_rivalry_bonus(seed):
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    db_session_factory = seed["db_session_factory"]
    await _make_conference(db_session_factory, league_id)
    await _set_rivalry_settings(db_session_factory, league_id, True, MATCHUP_WEEK, 7.0)
    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)

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
    assert len(rows) == 1
    assert rows[0].total_score == 17.0
