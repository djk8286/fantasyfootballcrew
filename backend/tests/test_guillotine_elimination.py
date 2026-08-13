"""
Tests for Guillotine's schedule/scoring adjustments and elimination
detection (Phase 4, "Guillotine + Custom Twist").

Step 2 (_effective_matchups, this file's first section): the
"stop-scoring slot" binding decision -- an eliminated team's already-
fixed schedule slot just stops producing a win/loss for weeks strictly
after its elimination, and once exactly two Guillotine teams remain
alive, they're force-paired directly every remaining week so the
finale actually plays out head-to-head (the classic round-robin's own
cycle wouldn't otherwise reliably re-pair them every week -- see
_effective_matchups' docstring in standings_service.py).

Step 3 (guillotine_service.process_league_guillotine, this file's
second section): elimination detection, tiebreak, CAS roster dump.

Uses a dedicated 4-team GUILLOTINE fixture (guillotine_seed), not the
shared 3-team `seed` fixture, since exercising "keeps eliminating while
>2 remain, then locks the finale" needs at least 4 teams. All rosters
start empty -- every test controls a team's score for a given week via
a flat_weekly Coach bonus (same trick test_rivalry_week.py/
test_standings_coach_bonus.py use), not real players/stats.
"""
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from app.models.coach import Coach, CoachPosition
from app.models.league import League, LeagueType
from app.models.player import Player
from app.models.team import Team
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services.standings_service import _effective_matchups, calculate_week, get_standings
from app.services.guillotine_service import process_league_guillotine
from app.models.notification import Notification, NotificationType


def _team(team_id: str, eliminated_week: int | None = None) -> Team:
    """A plain, unpersisted Team -- _effective_matchups only ever reads
    .id/.conference/.eliminated_week, so there's no need to touch the DB
    for the pure schedule-logic tests below."""
    return Team(id=team_id, name=team_id, league_id="league", roster=[],
                roster_version=0, conference=None, eliminated_week=eliminated_week)


def _guillotine_league(league_id: str = "league") -> League:
    return League(id=league_id, name="Guillotine Test", commissioner_id="commish",
                  league_type=LeagueType.GUILLOTINE)


def _standard_league(league_id: str = "league2") -> League:
    return League(id=league_id, name="Standard Test", commissioner_id="commish",
                  league_type=LeagueType.STANDARD)


# ─── Step 2: _effective_matchups ───────────────────────────────────────

def test_drops_pairing_with_earlier_eliminated_team():
    teams = [_team("t1"), _team("t2", eliminated_week=1), _team("t3"), _team("t4")]
    matchups = _effective_matchups(_guillotine_league(), teams, 2)
    ids_in_matchups = {tid for pair in matchups for tid in pair}
    assert "t2" not in ids_in_matchups


def test_keeps_pairing_for_team_eliminated_this_exact_week():
    # t2 is eliminated IN week 2 -- its own last stand still counts as a
    # real matchup for week 2 itself, only weeks after it are dropped.
    teams = [_team("t1"), _team("t2", eliminated_week=2), _team("t3"), _team("t4")]
    matchups = _effective_matchups(_guillotine_league(), teams, 2)
    ids_in_matchups = {tid for pair in matchups for tid in pair}
    assert "t2" in ids_in_matchups


def test_forces_finale_pairing_once_two_alive():
    teams = [_team("t1"), _team("t2", eliminated_week=1), _team("t3", eliminated_week=2), _team("t4")]
    matchups = _effective_matchups(_guillotine_league(), teams, 5)
    # Only t1/t4 are alive -- every other raw pairing that week involves
    # an eliminated team and gets dropped, so this must be the sole
    # matchup, forced if the raw schedule didn't already produce it.
    assert matchups == [("t1", "t4")]


def test_no_finale_force_for_non_guillotine_league():
    """Defensive: proves the finale-pairing override is gated on
    league_type specifically, not just "exactly 2 teams have
    eliminated_week set" -- eliminated_week should never actually be set
    on a non-Guillotine team in practice, but this pins the gate anyway."""
    teams = [_team("t1"), _team("t2", eliminated_week=1), _team("t3", eliminated_week=2), _team("t4")]
    matchups = _effective_matchups(_standard_league(), teams, 5)
    assert matchups == []


def test_effective_matchups_noop_when_nobody_eliminated():
    """Byte-for-byte the same as _build_league_schedule for a league
    where eliminated_week is None on every team (true for every league
    before Step 3 ever runs, and every non-Guillotine league forever)."""
    from app.services.standings_service import _build_league_schedule
    teams = [_team("t1"), _team("t2"), _team("t3"), _team("t4")]
    for week in range(1, 5):
        assert _effective_matchups(_guillotine_league(), teams, week) == _build_league_schedule(teams, week)


# ─── Step 2: DB-integration check (get_standings) ──────────────────────
# guillotine_seed now lives in conftest.py, shared across every Phase 4
# test file.

async def _add_coach(db_session_factory, team_id, bonus_type, bonus_value, position=CoachPosition.HC):
    async with db_session_factory() as db:
        db.add(Coach(id=str(uuid.uuid4()), name="Test Coach", position=position,
                     team_id=team_id, bonus_type=bonus_type, bonus_value=bonus_value))
        await db.commit()


async def _set_eliminated(db_session_factory, team_id, week):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.eliminated_week = week
        await db.commit()


@pytest.mark.asyncio
async def test_get_standings_stops_crediting_wins_after_elimination(guillotine_seed):
    """With 4 teams (t1..t4) inserted in that order, the round-robin's
    week-1 pairs are (t1,t4)/(t2,t3) and week-2's are (t1,t3)/(t4,t2)
    (verified directly against _build_round_robin_schedule's circle-
    method math). t2 is eliminated after week 1 -- its week-2 raw
    opponent, t4, should get NO matchup at all that week (a bye, not an
    extra unearned win/loss), so t4's record/points_against must stay
    exactly what it was after week 1."""
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _add_coach(db_session_factory, t3, "flat_weekly", 10.0)  # t3 outscores t2 week 1

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})
        standings_after_week1 = {s["team_id"]: s for s in await get_standings(league_id, db)}

    await _set_eliminated(db_session_factory, t2, 1)

    async with db_session_factory() as db:
        await calculate_week(league_id, 2, 2026, db, sleeper_stats={})
        standings_after_week2 = {s["team_id"]: s for s in await get_standings(league_id, db)}

    assert standings_after_week2[t4]["wins"] == standings_after_week1[t4]["wins"]
    assert standings_after_week2[t4]["losses"] == standings_after_week1[t4]["losses"]
    assert standings_after_week2[t4]["ties"] == standings_after_week1[t4]["ties"]
    assert standings_after_week2[t4]["points_against"] == standings_after_week1[t4]["points_against"]

    # t1/t3, whose week-2 pairing doesn't involve the eliminated t2 at
    # all, still get a completely normal week-2 result (proves the skip
    # is scoped to the eliminated team's own pairing, not a blanket
    # freeze of the whole week).
    assert standings_after_week2[t1]["wins"] + standings_after_week2[t1]["losses"] + standings_after_week2[t1]["ties"] == \
        standings_after_week1[t1]["wins"] + standings_after_week1[t1]["losses"] + standings_after_week1[t1]["ties"] + 1


# ─── Step 3: guillotine_service.process_league_guillotine ──────────────

async def _get_team(db_session_factory, team_id):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        return result.scalar_one()


async def _set_roster(db_session_factory, team_id, player_ids):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.roster = player_ids
        await db.commit()


async def _set_co_owner(db_session_factory, team_id, user_id):
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        team.co_owner_id = user_id
        await db.commit()


async def _run_guillotine(db_session_factory, league_id, year, week):
    async with db_session_factory() as db:
        league_result = await db.execute(select(League).where(League.id == league_id))
        league = league_result.scalar_one()
        return await process_league_guillotine(league, year, week, db)


@pytest.mark.asyncio
async def test_lowest_scorer_gets_eliminated(guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    # t1 gets a big bonus; t2/t3/t4 tie at 0 -- one of the tied three
    # must be the lowest scorer, never t1.
    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})

    result = await _run_guillotine(db_session_factory, league_id, 2026, 1)

    assert result is not None
    assert result["eliminated_team_id"] != t1
    assert result["week"] == 1

    eliminated = await _get_team(db_session_factory, result["eliminated_team_id"])
    assert eliminated.eliminated_week == 1
    survivor = await _get_team(db_session_factory, t1)
    assert survivor.eliminated_week is None


@pytest.mark.asyncio
async def test_elimination_dumps_roster_to_free_agency(guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id="sleeper-guillotine-1",
                         first_name="Cut", last_name="Player", position="RB")
        db.add(player)
        await db.commit()
        player_id = player.id

    await _set_roster(db_session_factory, t2, [player_id])
    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)  # keep t2/t3/t4 the tied-low group

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})

    result = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    assert result is not None

    eliminated = await _get_team(db_session_factory, result["eliminated_team_id"])
    assert eliminated.roster == []

    # The dumped player is now a free agent by the same exclusion
    # mechanism list_free_agents uses -- no team's roster contains it.
    async with db_session_factory() as db:
        all_teams = (await db.execute(select(Team).where(Team.league_id == league_id))).scalars().all()
    rostered_ids = {pid for t in all_teams for pid in (t.roster or [])}
    assert player_id not in rostered_ids


@pytest.mark.asyncio
async def test_elimination_notifies_owner_and_co_owner(guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    commissioner_id = guillotine_seed["commissioner_id"]
    db_session_factory = guillotine_seed["db_session_factory"]

    async with db_session_factory() as db:
        co_owner = User(id=str(uuid.uuid4()), email="co@test.local", username="co", hashed_password="x")
        db.add(co_owner)
        await db.commit()
        co_owner_id = co_owner.id
    await _set_co_owner(db_session_factory, t2, co_owner_id)
    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})

    result = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    assert result is not None
    eliminated_id = result["eliminated_team_id"]
    eliminated_owners = {commissioner_id}
    if eliminated_id == t2:
        eliminated_owners.add(co_owner_id)

    async with db_session_factory() as db:
        notif_result = await db.execute(
            select(Notification).where(Notification.type == NotificationType.TEAM_ELIMINATED)
        )
        notifications = notif_result.scalars().all()

    notified_user_ids = {n.user_id for n in notifications}
    assert commissioner_id in notified_user_ids  # every team's owner is the commissioner in this fixture
    if eliminated_id == t2:
        assert co_owner_id in notified_user_ids


@pytest.mark.asyncio
async def test_process_league_guillotine_is_idempotent(guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1 = guillotine_seed["team_ids"][0]
    db_session_factory = guillotine_seed["db_session_factory"]
    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})

    first = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    second = await _run_guillotine(db_session_factory, league_id, 2026, 1)

    assert first is not None
    assert second is None  # already processed this exact week

    async with db_session_factory() as db:
        result = await db.execute(
            select(Team).where(Team.league_id == league_id, Team.eliminated_week == 1)
        )
        eliminated_teams = result.scalars().all()
    assert len(eliminated_teams) == 1  # only one elimination ever recorded for week 1


@pytest.mark.asyncio
async def test_tiebreak_by_points_for_through_week(guillotine_seed):
    """t2/t3/t4 all tie at 0 on the raw week-1 score. t3 has extra
    cumulative points_for banked from an earlier (fabricated) week 0
    WeeklyScore row -- t2/t4 don't -- so the tiebreak must eliminate one
    of t2/t4, never the now-better-positioned t3."""
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)

    async with db_session_factory() as db:
        db.add(WeeklyScore(league_id=league_id, team_id=t3, week=0, year=2026,
                            total_score=50.0, lineup_data={}))
        await db.commit()

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})

    result = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    assert result is not None
    assert result["eliminated_team_id"] != t3
    assert result["eliminated_team_id"] != t1


@pytest.mark.asyncio
async def test_tiebreak_by_created_at_when_fully_tied(guillotine_seed):
    """t2/t3/t4 tie on both raw score and points_for-through-week (no
    earlier weeks at all) -- final tiebreak is earliest Team.created_at.
    t4 is backdated well before t2/t3, so it must be the one eliminated."""
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == t4))
        team4 = result.scalar_one()
        team4.created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        await db.commit()

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})

    result = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    assert result is not None
    assert result["eliminated_team_id"] == t4


@pytest.mark.asyncio
async def test_stops_eliminating_at_two_teams_remaining(guillotine_seed):
    league_id = guillotine_seed["league_id"]
    team_ids = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    # Week 1: eliminate one of the 4.
    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})
    r1 = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    assert r1 is not None

    # Week 2: eliminate another -- 2 remain.
    async with db_session_factory() as db:
        await calculate_week(league_id, 2, 2026, db, sleeper_stats={})
    r2 = await _run_guillotine(db_session_factory, league_id, 2026, 2)
    assert r2 is not None

    async with db_session_factory() as db:
        alive = (await db.execute(
            select(Team).where(Team.league_id == league_id, Team.eliminated_week.is_(None))
        )).scalars().all()
    assert len(alive) == 2

    # Week 3: finale reached -- no more eliminations, ever, even though
    # scoring keeps running.
    async with db_session_factory() as db:
        await calculate_week(league_id, 3, 2026, db, sleeper_stats={})
    r3 = await _run_guillotine(db_session_factory, league_id, 2026, 3)
    assert r3 is None

    async with db_session_factory() as db:
        alive_after = (await db.execute(
            select(Team).where(Team.league_id == league_id, Team.eliminated_week.is_(None))
        )).scalars().all()
    assert len(alive_after) == 2


@pytest.mark.asyncio
async def test_self_heals_a_missed_roster_dump(guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    db_session_factory = guillotine_seed["db_session_factory"]

    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id="sleeper-guillotine-2",
                         first_name="Ghost", last_name="Roster", position="RB")
        db.add(player)
        await db.commit()
        player_id = player.id

    # Simulate "eliminated, but the roster dump never landed" -- direct
    # mutation, bypassing process_league_guillotine's own CAS write.
    await _set_roster(db_session_factory, t2, [player_id])
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == t2))
        team2 = result.scalar_one()
        team2.eliminated_week = 1
        await db.commit()

    # A later call (week 2 -- no scores needed, self-heal runs before
    # any scoring check) should recover the roster on its own.
    await _run_guillotine(db_session_factory, league_id, 2026, 2)

    healed = await _get_team(db_session_factory, t2)
    assert healed.roster == []


@pytest.mark.asyncio
async def test_noop_for_non_guillotine_league(seed):
    """Uses the shared 3-team STANDARD `seed` fixture -- proves the
    league_type gate independent of everything else this function does."""
    league_id = seed["league_id"]
    db_session_factory = seed["db_session_factory"]

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})

    result = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    assert result is None


@pytest.mark.asyncio
async def test_noop_when_a_team_is_not_yet_scored(guillotine_seed):
    """No calculate_week call at all this week -- no WeeklyScore rows
    exist for any alive team, so this must not guess at an elimination."""
    league_id = guillotine_seed["league_id"]
    db_session_factory = guillotine_seed["db_session_factory"]

    result = await _run_guillotine(db_session_factory, league_id, 2026, 1)
    assert result is None


# ─── Step 4: wired into POST /standings/calculate (manual entry point) ──

@pytest.mark.asyncio
async def test_calculate_endpoint_returns_elimination_for_guillotine_league(client, guillotine_seed):
    league_id = guillotine_seed["league_id"]
    t1 = guillotine_seed["team_ids"][0]
    db_session_factory = guillotine_seed["db_session_factory"]
    await _add_coach(db_session_factory, t1, "flat_weekly", 20.0)

    client.headers["Authorization"] = f"Bearer {guillotine_seed['token']}"
    r = await client.post(f"/leagues/{league_id}/standings/calculate?week=1&year=2026")

    assert r.status_code == 200
    body = r.json()
    assert body["elimination"] is not None
    assert body["elimination"]["week"] == 1
    assert body["elimination"]["eliminated_team_id"] != t1


@pytest.mark.asyncio
async def test_calculate_endpoint_elimination_is_null_for_non_guillotine_league(client, seed):
    league_id = seed["league_id"]

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/standings/calculate?week=1&year=2026")

    assert r.status_code == 200
    assert r.json()["elimination"] is None
