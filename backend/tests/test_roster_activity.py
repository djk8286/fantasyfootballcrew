"""Team page data: records from standings (only finished weeks count),
pre-draft weeks left out of the schedule, GET /teams/{id}/roster and
GET /leagues/{id}/activity."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.league import DraftStatus, League, LeagueType
from app.models.nfl_game import NFLGame
from app.models.player import Player
from app.models.team import Team
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.team_activity_service import streak

YEAR = 2026
NOW = datetime.now(timezone.utc)


def _game(week, kickoff, completed):
    return NFLGame(id=str(uuid.uuid4()), espn_event_id=str(uuid.uuid4()), week=week, year=YEAR, season_type=2,
                   home_team="KC", home_team_name="KC", away_team="LV", away_team_name="LV",
                   status_state="post" if completed else "pre", status_detail="", completed=completed,
                   kickoff_at=kickoff)


async def _league(db_session_factory, *, weeks):
    """Two teams, so they meet every week. weeks: {week: (kickoff, completed,
    score_a, score_b)}; score None means no WeeklyScore rows. The draft
    finished a day before week 3's game, so weeks 1 and 2 are pre-draft."""
    async with db_session_factory() as db:
        alice = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username="alice", hashed_password="x")
        bob = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username="bob", hashed_password="x")
        league = League(id=str(uuid.uuid4()), name="L", commissioner_id=alice.id, league_type=LeagueType.STANDARD,
                        draft_status=DraftStatus.COMPLETED, scoring_config={}, roster_slots={})
        db.add_all([alice, bob, league])
        await db.flush()
        players = [Player(id=str(uuid.uuid4()), sleeper_id=f"s{i}-{uuid.uuid4().hex[:6]}", first_name=n, last_name="X",
                          position=pos, team="KC")
                   for i, (n, pos) in enumerate([("Amon", "WR"), ("Bijan", "RB"), ("Cam", "QB"), ("Drake", "WR")])]
        db.add_all(players)
        a = Team(id="team-a", name="Aces", league_id=league.id, owner_id=alice.id,
                 roster=[players[0].id, players[1].id], roster_version=0)
        b = Team(id="team-b", name="Bolts", league_id=league.id, owner_id=bob.id, is_cpu=False,
                 roster=[players[2].id, players[3].id], roster_version=0)
        db.add_all([a, b])
        for week, (kickoff, completed, sa, sb) in weeks.items():
            db.add(_game(week, kickoff, completed))
            if sa is not None:
                db.add_all([WeeklyScore(league_id=league.id, team_id="team-a", week=week, year=YEAR, total_score=sa),
                            WeeklyScore(league_id=league.id, team_id="team-b", week=week, year=YEAR, total_score=sb)])
        draft = Draft(id=str(uuid.uuid4()), league_id=league.id, status=DraftRunStatus.COMPLETED)
        db.add(draft)
        await db.flush()
        week3 = weeks.get(3, (NOW, False, None, None))[0]
        for i, (team, p) in enumerate([("team-a", players[0]), ("team-b", players[2]),
                                       ("team-b", players[3]), ("team-a", players[1])]):
            db.add(DraftPick(draft_id=draft.id, league_id=league.id, team_id=team, player_id=p.id,
                             round=i // 2 + 1, pick_number=i + 1, drafted_at=week3 - timedelta(days=1)))
        await db.commit()
        return {
            "league": league.id, "players": [p.id for p in players],
            "alice": {"Authorization": f"Bearer {create_access_token({'sub': alice.id, 'email': alice.email})}"},
            "bob": {"Authorization": f"Bearer {create_access_token({'sub': bob.id, 'email': bob.email})}"},
        }


def _season():
    """Weeks 1-2 before the draft. 3 and 4 are final (Aces win both),
    5 is live, 6 hasn't kicked off but calculate_week already wrote 0.00s."""
    return {
        1: (NOW - timedelta(days=35), True, None, None),
        2: (NOW - timedelta(days=28), True, None, None),
        3: (NOW - timedelta(days=21), True, 110.0, 90.5),
        4: (NOW - timedelta(days=14), True, 101.0, 99.0),
        5: (NOW - timedelta(hours=2), False, 40.0, 55.0),
        6: (NOW + timedelta(days=5), False, 0.0, 0.0),
    }


# ─── Standings and team reads ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_unplayed_and_live_weeks_dont_count_in_standings(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    body = (await client.get(f"/leagues/{s['league']}/standings")).json()
    rows = {r["team_id"]: r for r in body["standings"]}
    # Before: the week 6 0.00 rows made both teams 2-0-1 / 0-2-1, and the
    # live week 5 counted too.
    assert (rows["team-a"]["wins"], rows["team-a"]["losses"], rows["team-a"]["ties"]) == (2, 0, 0)
    assert (rows["team-b"]["wins"], rows["team-b"]["losses"], rows["team-b"]["ties"]) == (0, 2, 0)
    assert rows["team-a"]["points_for"] == 211.0 and rows["team-a"]["points_against"] == 189.5


@pytest.mark.asyncio
async def test_a_week_counts_once_its_last_game_is_long_over_even_if_never_marked_completed(client, db_session_factory):
    weeks = {3: (NOW - timedelta(days=2), False, 80.0, 70.0)}
    s = await _league(db_session_factory, weeks=weeks)
    rows = {r["team_id"]: r for r in (await client.get(f"/leagues/{s['league']}/standings")).json()["standings"]}
    assert rows["team-a"]["wins"] == 1


@pytest.mark.asyncio
async def test_team_reads_carry_points_for_and_against_from_standings(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    team = (await client.get("/teams/team-a")).json()
    assert (team["wins"], team["losses"], team["points_for"], team["points_against"]) == (2, 0, 211.0, 189.5)
    listed = {t["id"]: t for t in (await client.get(f"/teams/league/{s['league']}")).json()}
    assert listed["team-b"]["points_for"] == 189.5 and listed["team-b"]["losses"] == 2


@pytest.mark.asyncio
async def test_schedule_starts_at_the_draft_week_and_hides_unplayed_zeros(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    body = (await client.get(f"/leagues/{s['league']}/standings/schedule", params={"year": YEAR, "weeks": 6})).json()
    assert body["league_start_week"] == 3
    weeks = {w["week"]: w for w in body["schedule"]}
    assert sorted(weeks) == [3, 4, 5, 6]
    assert weeks[4]["status"] == "final" and weeks[5]["status"] == "live" and weeks[6]["status"] == "upcoming"
    sides = {m["team_a"]["id"]: m["team_a"] for m in weeks[6]["matchups"]} | {m["team_b"]["id"]: m["team_b"] for m in weeks[6]["matchups"]}
    assert sides["team-a"]["score"] is None
    live = {m["team_a"]["id"]: m["team_a"] for m in weeks[5]["matchups"]} | {m["team_b"]["id"]: m["team_b"] for m in weeks[5]["matchups"]}
    assert live["team-a"]["score"] == 40.0


# ─── GET /teams/{id}/roster ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_roster_endpoint_has_record_streak_owner_and_slots(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    r = await client.get("/teams/team-a/roster", params={"week": 6, "year": YEAR}, headers=s["bob"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["team"]["name"] == "Aces" and body["team"]["owner_username"] == "alice"
    assert body["record"] == {"wins": 2, "losses": 0, "ties": 0, "points_for": 211.0, "points_against": 189.5,
                              "rank": 1, "teams": 2, "streak": "W2"}
    assert body["league_start_week"] == 3
    by = {p["full_name"]: p for p in body["roster"]}
    assert set(by) == {"Amon X", "Bijan X"}
    assert {p["slot"] for p in body["roster"]} <= {"WR", "RB", "FLEX", "BN"}
    assert all("game" in p and "last_week_points" in p for p in body["roster"])


def test_streak_counts_back_from_the_latest_game():
    g = lambda w, a, b: {"year": YEAR, "week": w, "team_a": "x", "team_b": "y", "score_a": a, "score_b": b}
    assert streak([g(1, 1, 2), g(2, 3, 2), g(3, 5, 4)], "x") == "W2"
    assert streak([g(1, 1, 2), g(2, 3, 2), g(3, 5, 4)], "y") == "L2"
    assert streak([g(1, 2, 2)], "x") == "T1"
    assert streak([], "x") is None


# ─── GET /leagues/{id}/activity ─────────────────────────────────────────

async def _moves(db_session_factory, s):
    amon, bijan, cam, drake = s["players"]
    async with db_session_factory() as db:
        db.add_all([
            Transaction(league_id=s["league"], team_id="team-a", type=TransactionType.TRADE,
                        status=TransactionStatus.APPROVED, processed_at=NOW - timedelta(days=3),
                        details={"target_team_id": "team-b", "offered_player_ids": [amon], "requested_player_ids": [cam]}),
            Transaction(league_id=s["league"], team_id="team-b", type=TransactionType.WAIVER,
                        status=TransactionStatus.APPROVED, processed_at=NOW - timedelta(days=2),
                        details={"add_player_id": bijan, "drop_player_id": drake}),
            Transaction(id="claim-pending", league_id=s["league"], team_id="team-a", type=TransactionType.WAIVER,
                        status=TransactionStatus.PENDING, processed_at=NOW - timedelta(days=1),
                        details={"add_player_id": drake}),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_activity_resolves_names_and_hides_other_teams_pending_moves(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    await _moves(db_session_factory, s)

    texts = [i["text"] for i in (await client.get(f"/leagues/{s['league']}/activity", headers=s["bob"])).json()["items"]]
    assert texts == [
        "Bolts added Bijan X, dropping Drake X.",
        "Aces traded Amon X to Bolts for Cam X.",
        "Aces beat Bolts 101.00 to 99.00 in Week 4.",
        "Aces beat Bolts 110.00 to 90.50 in Week 3.",
        "The draft finished with 4 picks.",
    ]

    mine = (await client.get(f"/leagues/{s['league']}/activity", headers=s["alice"])).json()["items"]
    assert mine[0]["text"] == "Aces put in a claim for Drake X."
    assert mine[0]["status"] == "pending" and mine[0]["cancel"] == {"type": "claim", "id": "claim-pending"}
    assert mine[0]["players"][0]["name"] == "Drake X"


@pytest.mark.asyncio
async def test_team_activity_is_only_that_teams_moves_and_games(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    await _moves(db_session_factory, s)
    items = (await client.get(f"/leagues/{s['league']}/activity", params={"team_id": "team-b"})).json()["items"]
    kinds = [i["kind"] for i in items]
    assert kinds == ["claim", "trade", "result", "result", "draft"]
    assert items[-1]["text"] == "Bolts drafted 2 players, starting with Cam X."
    assert all("team-b" in i["team_ids"] for i in items)


@pytest.mark.asyncio
async def test_activity_404s_for_a_team_outside_the_league(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    r = await client.get(f"/leagues/{s['league']}/activity", params={"team_id": "nope"})
    assert r.status_code == 404
