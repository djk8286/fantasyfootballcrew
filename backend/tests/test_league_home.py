"""GET /leagues/{id}/home: the viewer's matchup (live or projected), top
lineup issue, last week's recap with bench points, scoreboard, standings
and activity."""
import pytest
from sqlalchemy import select

from app.models.league import League
from app.models.player_projection import PlayerProjection
from app.models.weekly_score import WeeklyScore
from app.services.league_home_service import scoring_label
from tests.test_roster_activity import YEAR, _league, _season

SCORING = {"receiving": {"rec_yd": 0.1, "rec": 1.0}, "rushing": {"rush_yd": 0.1}, "passing": {"pass_yd": 0.04}}


async def _home_league(db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    amon, bijan, cam, drake = s["players"]
    async with db_session_factory() as db:
        league = await db.get(League, s["league"])
        league.scoring_config = SCORING
        # Week 4: Aces scored 101 but started only Amon. Bijan sat with 30.
        ws = (await db.execute(select(WeeklyScore).where(
            WeeklyScore.team_id == "team-a", WeeklyScore.week == 4))).scalar_one()
        ws.lineup_data = {"total": 101.0, "breakdown": {
            amon: {"score": 101.0, "stats": {"rec_yd": 910, "rec": 10}, "position": "WR", "is_bench": False},
            bijan: {"score": 30.0, "stats": {"rush_yd": 300}, "position": "RB", "is_bench": True},
        }}
        db.add_all([
            PlayerProjection(player_id=amon, year=YEAR, week=6, stats={"rec_yd": 80, "rec": 6}),
            PlayerProjection(player_id=cam, year=YEAR, week=6, stats={"pass_yd": 250}),
        ])
        await db.commit()
    return s


@pytest.mark.asyncio
async def test_guest_gets_the_league_but_nothing_personal(client, db_session_factory):
    s = await _home_league(db_session_factory)
    r = await client.get(f"/leagues/{s['league']}/home", params={"week": 6, "year": YEAR})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["league"]["scoring"] == "PPR" and body["league"]["team_count"] == 2
    assert body["league"]["is_commissioner"] is False
    assert body["my_team"] is None and body["my_matchup"] is None and body["last_week"] is None
    assert len(body["scoreboard"]) == 1 and body["scoreboard"][0]["mine"] is False
    assert [row["name"] for row in body["standings"]] == ["Aces", "Bolts"]
    assert body["standings"][0]["streak"] == "W2"
    assert body["activity"][-1]["kind"] == "draft"


@pytest.mark.asyncio
async def test_upcoming_week_shows_projections_not_zeros(client, db_session_factory):
    s = await _home_league(db_session_factory)
    body = (await client.get(f"/leagues/{s['league']}/home", params={"week": 6, "year": YEAR}, headers=s["alice"])).json()
    assert body["week_status"] == "upcoming"
    assert body["league"]["is_commissioner"] is True and body["league"]["is_member"] is True
    me, opp = body["my_matchup"]["me"], body["my_matchup"]["opponent"]
    assert (me["name"], opp["name"]) == ("Aces", "Bolts")
    assert me["score"] is None and opp["score"] is None  # the 0.00 rows aren't scores yet
    assert me["projected"] == 14.0 and opp["projected"] == 10.0
    assert body["scoreboard"][0]["mine"] is True


@pytest.mark.asyncio
async def test_top_issue_and_recap_with_bench_points(client, db_session_factory):
    s = await _home_league(db_session_factory)
    body = (await client.get(f"/leagues/{s['league']}/home", params={"week": 6, "year": YEAR}, headers=s["alice"])).json()
    assert body["issue_count"] >= 1
    assert body["top_issue"]["kind"] == "empty"  # a 2-man roster can't fill QB
    assert body["last_week"] == {
        "week": 4, "result": "W", "score": 101.0, "opponent_score": 99.0,
        "opponent_team_id": "team-b", "opponent_name": "Bolts",
        "optimal_score": 131.0, "bench_points": 30.0,
    }


@pytest.mark.asyncio
async def test_live_week_shows_live_scores(client, db_session_factory):
    s = await _home_league(db_session_factory)
    body = (await client.get(f"/leagues/{s['league']}/home", params={"week": 5, "year": YEAR}, headers=s["bob"])).json()
    assert body["week_status"] == "live"
    assert body["my_matchup"]["me"]["name"] == "Bolts" and body["my_matchup"]["me"]["score"] == 55.0
    assert body["league"]["is_commissioner"] is False


@pytest.mark.asyncio
async def test_unknown_league_404s(client):
    r = await client.get("/leagues/nope/home", params={"week": 6, "year": YEAR})
    assert r.status_code == 404


def test_scoring_label():
    assert scoring_label({"receiving": {"rec": 1}}) == "PPR"
    assert scoring_label({"receiving": {"rec": 0.5}}) == "Half PPR"
    assert scoring_label({"receiving": {"rec_yd": 0.1}}) == "Standard"
    assert scoring_label(None) == "Standard"
