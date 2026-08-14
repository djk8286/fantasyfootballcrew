"""
Tests for AI Co-Commissioner v1 Phase 2 Step 1 -- scoring_engine's
calculate_player_score_by_category and insights_service.py's
compute_scoring_insights (pure arithmetic, zero LLM calls, no mocking
needed -- same testing style as test_league_health.py), plus the
GET /leagues/{id}/commissioner/insights endpoint.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.coach import Coach, CoachPosition
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.scoring_engine import calculate_player_score, calculate_player_score_by_category
from app.services.insights_service import (
    compute_scoring_insights,
    MIN_WEEKS_FOR_INSIGHTS,
    HIGH_VARIANCE_CV,
    OVERPOWERED_BONUS_SHARE,
    POSITIONAL_GAP_RATIO,
)

YEAR = 2026


async def _make_league(db_session_factory, extra_kwargs=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"insightscommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        kwargs = {"scoring_config": {}, "roster_slots": {}, **(extra_kwargs or {})}
        league = League(id=str(uuid.uuid4()), name="Insights Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, **kwargs)
        db.add(league)
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"league_id": league.id, "commissioner_id": commissioner.id, "token": token}


async def _add_team(db_session_factory, league_id):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name=f"Team {uuid.uuid4().hex[:6]}", league_id=league_id,
                    roster=[], roster_version=0)
        db.add(team)
        await db.commit()
        return team.id


async def _add_weekly_score(db_session_factory, league_id, team_id, week, lineup_data=None, total_score=0.0, year=YEAR):
    async with db_session_factory() as db:
        db.add(WeeklyScore(league_id=league_id, team_id=team_id, week=week, year=year,
                            total_score=total_score, lineup_data=lineup_data or {}))
        await db.commit()


async def _add_coach(db_session_factory, team_id, bonus_type, bonus_value=5.0):
    async with db_session_factory() as db:
        db.add(Coach(team_id=team_id, name="Coach", position=CoachPosition.HC,
                      bonus_type=bonus_type, bonus_value=bonus_value, is_active=True))
        await db.commit()


# ─── calculate_player_score_by_category regression pin ─────────────

def test_category_breakdown_sums_to_the_same_total_as_calculate_player_score():
    scoring_config = {
        "passing": {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2},
        "rushing": {"rush_yd": 0.1, "rush_td": 6},
        "bonus": {"pass_300_yds": 3},
        "custom": [{"stat_name": "rush_yd", "operator": "gte", "threshold": 100, "points": 3, "multiplier": 1}],
    }
    stats = {"pass_yd": 320, "pass_td": 2, "pass_int": 1, "rush_yd": 120, "rush_td": 1}

    total = calculate_player_score(stats, scoring_config)
    by_category = calculate_player_score_by_category(stats, scoring_config)

    assert sum(by_category.values()) == pytest.approx(total, abs=0.05)


def test_category_breakdown_empty_for_empty_stats():
    assert calculate_player_score_by_category({}, {"passing": {"pass_yd": 0.04}}) == {}


# ─── compute_scoring_insights ───────────────────────────────────────

@pytest.mark.asyncio
async def test_not_enough_weeks_returns_unavailable(db_session_factory):
    setup = await _make_league(db_session_factory)
    team_id = await _add_team(db_session_factory, setup["league_id"])
    await _add_weekly_score(db_session_factory, setup["league_id"], team_id, 1)
    await _add_weekly_score(db_session_factory, setup["league_id"], team_id, 2)

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        insights = await compute_scoring_insights(league, db)

    assert insights == {"available": False, "weeks_available": 2, "weeks_required": MIN_WEEKS_FOR_INSIGHTS}


@pytest.mark.asyncio
async def test_category_variance_flags_a_lopsided_category(db_session_factory):
    scoring_config = {"passing": {"pass_yd": 0.04}, "rushing": {"rush_yd": 0.1}}
    setup = await _make_league(db_session_factory, extra_kwargs={"scoring_config": scoring_config})
    team_id = await _add_team(db_session_factory, setup["league_id"])

    # "passing" stays perfectly constant (10 pts every week) -- zero
    # variance. "rushing" swings wildly week to week -- high variance.
    rush_yds_by_week = {1: 0, 2: 50, 3: 300, 4: 10}
    for week, rush_yd in rush_yds_by_week.items():
        breakdown = {"p1": {"stats": {"pass_yd": 250, "rush_yd": rush_yd}, "position": "QB", "score": 10.0 + rush_yd * 0.1}}
        await _add_weekly_score(db_session_factory, setup["league_id"], team_id, week,
                                 lineup_data={"breakdown": breakdown})

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        insights = await compute_scoring_insights(league, db)

    assert insights["available"] is True
    flagged_categories = {o["category"] for o in insights["category_variance"]}
    assert "rushing" in flagged_categories
    assert "passing" not in flagged_categories
    rushing_obs = next(o for o in insights["category_variance"] if o["category"] == "rushing")
    assert rushing_obs["coefficient_of_variation"] >= HIGH_VARIANCE_CV


@pytest.mark.asyncio
async def test_coach_bonus_impact_only_evaluates_configured_bonus_types(db_session_factory):
    setup = await _make_league(db_session_factory)
    team_id = await _add_team(db_session_factory, setup["league_id"])
    await _add_coach(db_session_factory, team_id, bonus_type="flat_weekly")
    # No coach configured with bonus_type="win_bonus" -- even though
    # lineup_data below carries a win_bonus key, it must not appear in
    # the output at all.

    for week in (1, 2, 3):
        await _add_weekly_score(db_session_factory, setup["league_id"], team_id, week,
                                 total_score=100.0, lineup_data={"coach_bonus": 20.0, "win_bonus": 5.0})

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        insights = await compute_scoring_insights(league, db)

    bonus_types_seen = {o["bonus_type"] for o in insights["coach_bonus_impact"]}
    assert bonus_types_seen == {"flat_weekly"}
    flat_weekly_obs = next(o for o in insights["coach_bonus_impact"] if o["bonus_type"] == "flat_weekly")
    assert flat_weekly_obs["share_of_average_score"] >= OVERPOWERED_BONUS_SHARE


@pytest.mark.asyncio
async def test_positional_balance_flags_a_known_gap(db_session_factory):
    setup = await _make_league(db_session_factory)
    team_id = await _add_team(db_session_factory, setup["league_id"])

    for week in (1, 2, 3):
        breakdown = {
            "qb1": {"stats": {}, "position": "QB", "score": 30.0},
            "k1": {"stats": {}, "position": "K", "score": 5.0},
        }
        await _add_weekly_score(db_session_factory, setup["league_id"], team_id, week,
                                 lineup_data={"breakdown": breakdown})

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == setup["league_id"]))).scalar_one()
        insights = await compute_scoring_insights(league, db)

    assert len(insights["positional_balance"]) == 1
    gap = insights["positional_balance"][0]
    assert gap["highest_position"] == "QB"
    assert gap["lowest_position"] == "K"
    assert gap["highest_average"] / gap["lowest_average"] >= POSITIONAL_GAP_RATIO


@pytest.mark.asyncio
async def test_insights_endpoint_commissioner_only(client, db_session_factory):
    setup = await _make_league(db_session_factory)
    team_id = await _add_team(db_session_factory, setup["league_id"])
    for week in (1, 2, 3):
        await _add_weekly_score(db_session_factory, setup["league_id"], team_id, week, total_score=50.0)

    outsider = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                     username=f"insightsoutsider{uuid.uuid4().hex[:6]}", hashed_password="x")
    async with db_session_factory() as db:
        db.add(outsider)
        await db.commit()
    outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/insights")
    assert r.status_code == 403

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.get(f"/leagues/{setup['league_id']}/commissioner/insights")
    assert r.status_code == 200
    assert r.json()["available"] is True
