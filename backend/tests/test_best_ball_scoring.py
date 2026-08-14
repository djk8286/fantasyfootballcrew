"""
Tests for calculate_week's Best-Ball scoring integration (Phase 6 Step
4, "Best-Ball Hybrid") -- the highest-risk step in this phase, since it
touches the shared scoring path every league type flows through.

For a clean, position-agnostic way to control a player's exact score
regardless of position, these tests use a "generic" scoring category
(`{"generic": {"pts": 1.0}}`) with each player's stats set to
`{"pts": <desired score>}` -- calculate_player_score iterates every
category in scoring_config as a flat stat_name->points_per_unit dict,
so this works identically for any position, letting a roster's optimal-
vs-whole-roster totals be predicted exactly.

Decoupling-proof tests (Guillotine/Rivalry Week/Salary-Cap) reuse the
existing seed/guillotine_seed fixtures + the established flat_weekly
Coach-bonus trick those phases' own tests already use to control a
team's base score, rather than re-deriving a full scored roster for
each -- consistent with this codebase's established test style.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.coach import Coach, CoachPosition
from app.models.league import League, LeagueType
from app.models.lineup import Lineup
from app.models.player import Player
from app.models.team import Team
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.scoring_engine import calculate_optimal_lineup, DEFAULT_ROSTER_SLOTS
from app.services.standings_service import calculate_week
from app.services.guillotine_service import process_league_guillotine

WEEK = 1
YEAR = 2026
GENERIC_SCORING = {"generic": {"pts": 1.0}}

# 11-player roster, distinct scores by design so the optimal 9-starter
# subset (QB1/RB2/WR2/TE1/FLEX1/K1/DEF1, DEFAULT_ROSTER_SLOTS) is
# unambiguous: QB2 (pts=5) and WR3 (pts=2) are the two lowest-scoring
# flex-ineligible-or-not players and get benched.
ROSTER_SPEC = [
    ("QB1", "QB", 20), ("QB2", "QB", 5),
    ("RB1", "RB", 18), ("RB2", "RB", 16), ("RB3", "RB", 3),
    ("WR1", "WR", 17), ("WR2", "WR", 15), ("WR3", "WR", 2),
    ("TE1", "TE", 14),
    ("K1", "K", 8),
    ("DEF1", "DEF", 9),
]


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        return user


async def _make_scored_roster_league(db_session_factory, best_ball_enabled=True, extra_settings=None):
    """A single-team STANDARD league with the 11-player ROSTER_SPEC
    above, real generic scoring, and best_ball_settings as given.
    Returns (league_id, team_id, sleeper_stats, players_by_label)."""
    async with db_session_factory() as db:
        commissioner = await _make_user(db_session_factory)
        league_settings = {"enabled": best_ball_enabled}
        if extra_settings:
            league_settings.update(extra_settings)
        league = League(id=str(uuid.uuid4()), name="Best Ball Scoring Test League",
                         commissioner_id=commissioner.id, league_type=LeagueType.STANDARD,
                         scoring_config=GENERIC_SCORING, roster_slots={},
                         best_ball_settings=league_settings)
        db.add(league)
        await db.flush()

        players_by_label = {}
        sleeper_stats = {}
        roster_ids = []
        for label, position, pts in ROSTER_SPEC:
            player = Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-{label}-{uuid.uuid4().hex[:6]}",
                             first_name=label, last_name="Test", position=position)
            db.add(player)
            await db.flush()
            players_by_label[label] = player
            sleeper_stats[player.sleeper_id] = {"pts": pts}
            roster_ids.append(player.id)

        team = Team(id=str(uuid.uuid4()), name="Only Team", league_id=league.id,
                     owner_id=commissioner.id, roster=roster_ids, roster_version=0)
        db.add(team)
        await db.commit()

        return league.id, team.id, sleeper_stats, players_by_label


async def _score_for(db_session_factory, league_id, team_id, week=WEEK, year=YEAR):
    async with db_session_factory() as db:
        result = await db.execute(
            select(WeeklyScore).where(
                WeeklyScore.league_id == league_id, WeeklyScore.team_id == team_id,
                WeeklyScore.week == week, WeeklyScore.year == year,
            )
        )
        return result.scalar_one_or_none()


def _expected_optimal(players_by_label, sleeper_stats):
    roster_for_optimizer = {
        p.id: {"stats": sleeper_stats[p.sleeper_id], "position": p.position, "name": p.id}
        for p in players_by_label.values()
    }
    slot_kwargs = {f"n_{k.lower()}": v for k, v in DEFAULT_ROSTER_SLOTS.items()}
    return calculate_optimal_lineup(roster_for_optimizer, GENERIC_SCORING, **slot_kwargs)


@pytest.mark.asyncio
async def test_best_ball_uses_optimal_lineup_score(db_session_factory):
    league_id, team_id, sleeper_stats, players_by_label = await _make_scored_roster_league(db_session_factory)

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats=sleeper_stats)

    score = await _score_for(db_session_factory, league_id, team_id)
    expected = _expected_optimal(players_by_label, sleeper_stats)
    assert score.total_score == expected["optimal_score"]
    # Sanity: the optimizer really did exclude some bench players, i.e.
    # this isn't accidentally just "the whole roster summed" too.
    assert score.total_score < sum(pts for _, _, pts in ROSTER_SPEC)


@pytest.mark.asyncio
async def test_auto_starters_matches_optimizer_picks(db_session_factory):
    league_id, team_id, sleeper_stats, players_by_label = await _make_scored_roster_league(db_session_factory)

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats=sleeper_stats)

    score = await _score_for(db_session_factory, league_id, team_id)
    expected = _expected_optimal(players_by_label, sleeper_stats)
    expected_ids = {a["player_id"] for a in expected["lineup"]}

    assert score.lineup_data["auto_lineup"] is True
    assert set(score.lineup_data["auto_starters"]) == expected_ids
    # The two lowest scorers (QB2 pts=5, WR3 pts=2) must be benched.
    assert players_by_label["QB2"].id not in score.lineup_data["auto_starters"]
    assert players_by_label["WR3"].id not in score.lineup_data["auto_starters"]


@pytest.mark.asyncio
async def test_existing_lineup_row_ignored_for_best_ball(db_session_factory):
    league_id, team_id, sleeper_stats, players_by_label = await _make_scored_roster_league(db_session_factory)

    # A saved Lineup naming the WORST players as starters -- if this were
    # honored at all, the score would be far lower than the optimal.
    bogus_starters = [players_by_label["QB2"].id, players_by_label["WR3"].id, players_by_label["RB3"].id]
    async with db_session_factory() as db:
        db.add(Lineup(id=str(uuid.uuid4()), team_id=team_id, week=WEEK, year=YEAR, starters=bogus_starters))
        await db.commit()

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats=sleeper_stats)

    score = await _score_for(db_session_factory, league_id, team_id)
    expected = _expected_optimal(players_by_label, sleeper_stats)
    assert score.total_score == expected["optimal_score"]


@pytest.mark.asyncio
async def test_non_best_ball_league_scores_whole_roster_unaffected(db_session_factory):
    """Regression pin: a league with best_ball disabled must be
    byte-for-byte the pre-existing "no Lineup row -> score the WHOLE
    roster" behavior, with no auto_lineup/auto_starters key at all."""
    league_id, team_id, sleeper_stats, players_by_label = await _make_scored_roster_league(
        db_session_factory, best_ball_enabled=False
    )

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats=sleeper_stats)

    score = await _score_for(db_session_factory, league_id, team_id)
    assert score.total_score == sum(pts for _, _, pts in ROSTER_SPEC)
    assert "auto_lineup" not in score.lineup_data
    assert "auto_starters" not in score.lineup_data


# ─── Decoupling-proof tests ─────────────────────────────────────────────

async def _add_coach(db_session_factory, team_id, bonus_type, bonus_value, position=CoachPosition.HC):
    async with db_session_factory() as db:
        db.add(Coach(id=str(uuid.uuid4()), name="Test Coach", position=position,
                     team_id=team_id, bonus_type=bonus_type, bonus_value=bonus_value))
        await db.commit()


@pytest.mark.asyncio
async def test_guillotine_decoupling(guillotine_seed):
    """Guillotine elimination reads only WeeklyScore.total_score --
    confirm it still works correctly (eliminates the true lowest
    scorer) when best_ball is also enabled on the same league, even
    with empty rosters (best-ball's optimizer path is a no-op for an
    empty roster, same as the pre-existing empty-roster branch)."""
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.best_ball_settings = {"enabled": True}
        await db.commit()

    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)
    await _add_coach(db_session_factory, t2, "flat_weekly", 15.0)
    await _add_coach(db_session_factory, t3, "flat_weekly", 10.0)
    await _add_coach(db_session_factory, t4, "flat_weekly", 1.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats={})

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        elimination = await process_league_guillotine(league, YEAR, WEEK, db)

    assert elimination is not None
    assert elimination["eliminated_team_id"] == t4


@pytest.mark.asyncio
async def test_rivalry_week_decoupling(seed):
    """Rivalry Week's bonus runs on base_totals computed AFTER Pass 1 --
    confirm it still applies correctly on top of a best-ball-computed
    base score."""
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    db_session_factory = seed["db_session_factory"]
    MATCHUP_WEEK = 3  # see test_matchup_notifications.py's own convention

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.league_type = LeagueType.CONFERENCE
        league.best_ball_settings = {"enabled": True}
        league.rivalry_week_settings = {"enabled": True, "week": MATCHUP_WEEK, "bonus_value": 7.0}
        await db.commit()

    await _add_coach(db_session_factory, team_a, "flat_weekly", 10.0)  # forces team_a to win on base score

    async with db_session_factory() as db:
        await calculate_week(league_id, MATCHUP_WEEK, 2026, db, sleeper_stats={})

    score_a = await _score_for(db_session_factory, league_id, team_a, MATCHUP_WEEK, 2026)
    assert score_a.total_score == 17.0  # 10.0 base (best-ball path, empty roster -> 0) + 7.0 rivalry
    assert score_a.lineup_data["rivalry_bonus"] == 7.0


@pytest.mark.asyncio
async def test_salary_cap_and_best_ball_coexist(db_session_factory):
    """Salary-Cap is purely a roster-CONSTRUCTION-time gate -- confirm a
    league with BOTH salary_cap_settings.enabled and
    best_ball_settings.enabled scores correctly with no interaction
    error (cap constrains what's rostered elsewhere; best-ball still
    just picks the per-week-optimal subset of whatever's rostered)."""
    league_id, team_id, sleeper_stats, players_by_label = await _make_scored_roster_league(db_session_factory)

    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.salary_cap_settings = {"enabled": True}
        await db.commit()

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats=sleeper_stats)

    score = await _score_for(db_session_factory, league_id, team_id)
    expected = _expected_optimal(players_by_label, sleeper_stats)
    assert score.total_score == expected["optimal_score"]
    assert score.lineup_data["auto_lineup"] is True
