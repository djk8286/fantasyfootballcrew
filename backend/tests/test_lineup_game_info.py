"""GET /teams/{id}/lineup: each player's game this week (opponent, kickoff,
status, lock), bye flag and last week's points."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.league import DraftStatus, League, LeagueType
from app.models.nfl_game import NFLGame
from app.models.player import Player
from app.models.team import Team
from app.models.user import User

YEAR, WEEK = 2026, 7
SCORING = {"generic": {"pts": 1.0}}


def _game(home, away, kickoff, state="pre", completed=False, detail=""):
    return NFLGame(id=str(uuid.uuid4()), espn_event_id=str(uuid.uuid4()), week=WEEK, year=YEAR, season_type=2,
                   home_team=home, home_team_name=home, away_team=away, away_team_name=away,
                   status_state=state, status_detail=detail, completed=completed, kickoff_at=kickoff)


async def _seed(db_session_factory, players, games):
    async with db_session_factory() as db:
        owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        league = League(id=str(uuid.uuid4()), name="L", commissioner_id=owner.id, league_type=LeagueType.STANDARD,
                        draft_status=DraftStatus.COMPLETED, scoring_config=SCORING, roster_slots={})
        db.add_all([owner, league])
        await db.flush()
        ids = {}
        for label, pos, nfl, week_stats, stats_year in players:
            p = Player(id=str(uuid.uuid4()), sleeper_id=f"s-{label}-{uuid.uuid4().hex[:6]}", first_name=label, last_name="X",
                       position=pos, team=nfl, stats_year=stats_year, week_stats=week_stats)
            db.add(p)
            ids[label] = p.id
        team = Team(id=str(uuid.uuid4()), name="T", league_id=league.id, owner_id=owner.id, roster=list(ids.values()), roster_version=0)
        db.add(team)
        db.add_all(games)
        await db.commit()
        return team.id, ids


async def _roster(client, team_id):
    r = await client.get(f"/teams/{team_id}/lineup", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
    body = r.json()
    return body, {p["full_name"].split()[0]: p for p in body["roster"]}


@pytest.mark.asyncio
async def test_each_player_gets_opponent_kickoff_and_lock(client, db_session_factory):
    now = datetime.now(timezone.utc)
    sunday = now + timedelta(days=3)
    team_id, _ = await _seed(db_session_factory, [
        ("Home", "QB", "KC", {}, YEAR),
        ("Away", "WR", "LV", {}, YEAR),
        ("Live", "RB", "SF", {}, YEAR),
        ("Done", "TE", "DAL", {}, YEAR),
    ], [
        _game("KC", "LV", sunday, detail="Sun 1:00 PM"),
        _game("SF", "SEA", now - timedelta(hours=1), state="in", detail="Q2 3:10"),
        _game("PHI", "DAL", now - timedelta(days=3), state="post", completed=True, detail="Final"),
    ])
    body, by = await _roster(client, team_id)
    assert body["schedule_known"] is True

    assert by["Home"]["game"] == {"opponent": "LV", "home": True, "kickoff_at": sunday.isoformat(),
                                  "status": "pre", "detail": "Sun 1:00 PM", "locked": False}
    assert by["Away"]["game"]["opponent"] == "KC" and by["Away"]["game"]["home"] is False
    assert by["Live"]["game"]["status"] == "in" and by["Live"]["game"]["locked"] is True
    assert by["Done"]["game"]["status"] == "post" and by["Done"]["game"]["locked"] is True
    assert not any(p["on_bye"] for p in by.values())


@pytest.mark.asyncio
async def test_game_locks_once_kickoff_time_passes_even_if_status_is_stale(client, db_session_factory):
    team_id, _ = await _seed(db_session_factory, [("Stale", "QB", "KC", {}, YEAR)],
                             [_game("KC", "LV", datetime.now(timezone.utc) - timedelta(minutes=2))])
    _, by = await _roster(client, team_id)
    assert by["Stale"]["game"]["status"] == "pre"
    assert by["Stale"]["game"]["locked"] is True


@pytest.mark.asyncio
async def test_bye_is_derived_from_the_schedule(client, db_session_factory):
    team_id, _ = await _seed(db_session_factory, [
        ("Bye", "WR", "LAC", {}, YEAR),
        ("Plays", "WR", "KC", {}, YEAR),
        ("Free", "WR", None, {}, YEAR),
    ], [_game("KC", "LV", datetime.now(timezone.utc) + timedelta(days=2))])
    _, by = await _roster(client, team_id)
    assert by["Bye"]["on_bye"] is True and by["Bye"]["game"] is None
    assert by["Plays"]["on_bye"] is False
    assert by["Free"]["on_bye"] is False and by["Free"]["game"] is None


@pytest.mark.asyncio
async def test_unknown_schedule_puts_nobody_on_bye(client, db_session_factory):
    team_id, _ = await _seed(db_session_factory, [("Any", "WR", "LAC", {}, YEAR)], [])
    body, by = await _roster(client, team_id)
    assert body["schedule_known"] is False
    assert by["Any"]["on_bye"] is False and by["Any"]["game"] is None


@pytest.mark.asyncio
async def test_washington_matches_espn_wsh_game(client, db_session_factory):
    team_id, _ = await _seed(db_session_factory, [("Wash", "QB", "WAS", {}, YEAR)],
                             [_game("WSH", "DAL", datetime.now(timezone.utc) + timedelta(days=2))])
    _, by = await _roster(client, team_id)
    assert by["Wash"]["on_bye"] is False
    assert by["Wash"]["game"]["opponent"] == "DAL"


@pytest.mark.asyncio
async def test_last_week_points_scored_with_league_rules(client, db_session_factory):
    team_id, _ = await _seed(db_session_factory, [
        ("Played", "RB", "KC", {"5": {"pts": 3}, "6": {"pts": 12.5}}, YEAR),
        ("Missed", "RB", "KC", {"5": {"pts": 9}}, YEAR),
        ("OldSeason", "RB", "KC", {"6": {"pts": 20}}, YEAR - 1),
    ], [])
    _, by = await _roster(client, team_id)
    assert by["Played"]["last_week_points"] == 12.5
    assert by["Missed"]["last_week_points"] is None
    assert by["OldSeason"]["last_week_points"] is None
