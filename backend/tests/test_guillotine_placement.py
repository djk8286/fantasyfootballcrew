"""Guillotine final placement (guillotine_placement.py) and how
get_standings orders a Guillotine league by it. The finale series
decides the champion, not total wins."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.team import Team
from app.models.weekly_score import WeeklyScore
from app.services.guillotine_placement import guillotine_placement, order_guillotine_rows
from app.services.standings_service import get_standings, get_standings_detail

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _t(tid, cut=None, order=0):
    return SimpleNamespace(id=tid, eliminated_week=cut, created_at=T0 + timedelta(minutes=order))


def _weeks(rows):
    """{week: {tid: score}} -> {(2026, week): ...}"""
    return {(2026, w): s for w, s in rows.items()}


TEAMS = [_t("a", order=0), _t("b", order=1), _t("c", cut=2, order=2), _t("d", cut=1, order=3)]


def test_finale_in_progress_has_no_champion_and_leader_first():
    scores = _weeks({1: {"a": 90, "b": 80, "c": 70, "d": 10}, 2: {"a": 90, "b": 80, "c": 5},
                     3: {"a": 100, "b": 110}, 4: {"a": 100, "b": 120}, 5: {"a": 130, "b": 90}})
    p = guillotine_placement(TEAMS, scores, {"a": 510, "b": 480, "c": 75, "d": 10})
    assert p["phase"] == "finale"
    assert p["champion_team_id"] is None
    assert p["finale_weeks"] == [3, 4, 5]
    assert [f["team_id"] for f in p["finalists"]] == ["b", "a"]
    assert (p["finalists"][0]["wins"], p["finalists"][0]["losses"]) == (2, 1)
    assert p["places"] == {"a": None, "b": None, "c": 3, "d": 4}
    assert p["order"] == ["b", "a", "c", "d"]


def test_series_winner_is_champion_even_with_fewer_total_wins():
    # a has far more season wins and points; b takes the finale series 9-7.
    finale = {}
    for w in range(3, 19):
        b_wins = (w - 3) < 9
        finale[w] = {"a": 100, "b": 101} if b_wins else {"a": 150, "b": 90}
    scores = _weeks({1: {"a": 200, "b": 50, "c": 60, "d": 40}, 2: {"a": 200, "b": 50, "c": 40}, **finale})
    p = guillotine_placement(TEAMS, scores, {"a": 3000, "b": 1500, "c": 100, "d": 40})
    assert p["phase"] == "final"
    assert p["champion_team_id"] == "b"
    assert p["runner_up_team_id"] == "a"
    assert p["places"] == {"b": 1, "a": 2, "c": 3, "d": 4}


def test_even_series_goes_to_finale_points_then_season_points():
    scores = _weeks({3: {"a": 100, "b": 90}, 18: {"a": 80, "b": 95}})
    p = guillotine_placement(TEAMS, scores, {"a": 1000, "b": 900})
    assert p["champion_team_id"] == "b"  # 1-1, b has 185 to a's 180

    level = _weeks({3: {"a": 100, "b": 90}, 18: {"a": 90, "b": 100}})
    p = guillotine_placement(TEAMS, level, {"a": 900, "b": 1000})
    assert p["champion_team_id"] == "b"  # 1-1, 190 each, b has more season points


def test_weeks_where_finalists_did_not_meet_are_not_in_the_series():
    scores = _weeks({3: {"a": 100, "b": 90}, 4: {"a": 100, "b": 90}, 5: {"a": 50, "b": 90}})
    p = guillotine_placement(TEAMS, scores, {"a": 250, "b": 270}, is_pairing=lambda w, x, y: w != 4)
    assert p["finale_weeks"] == [3, 5]
    assert {f["team_id"]: f["wins"] for f in p["finalists"]} == {"a": 1, "b": 1}


def test_before_the_finale_alive_teams_keep_standings_order():
    teams = [_t("a"), _t("b"), _t("c"), _t("d", cut=1)]
    p = guillotine_placement(teams, _weeks({1: {"a": 1, "b": 2, "c": 3, "d": 0}}), {})
    assert p["phase"] == "elimination"
    assert p["places"] == {"a": None, "b": None, "c": None, "d": 4}
    rows = [{"team_id": t, "eliminated_week": cut} for t, cut in
            [("d", 1), ("c", None), ("a", None), ("b", None)]]
    out = order_guillotine_rows(rows, p)
    assert [r["team_id"] for r in out] == ["c", "a", "b", "d"]
    assert out[-1]["guillotine_place"] == 4


async def _seed_scores(factory, league_id, by_week):
    async with factory() as db:
        for w, scores in by_week.items():
            for tid, pts in scores.items():
                db.add(WeeklyScore(league_id=league_id, team_id=tid, week=w, year=2026,
                                   total_score=pts, lineup_data={}))
        await db.commit()


@pytest.mark.asyncio
async def test_get_standings_ranks_the_series_winner_first(guillotine_seed):
    factory, league_id = guillotine_seed["db_session_factory"], guillotine_seed["league_id"]
    t1, t2, t3, t4 = guillotine_seed["team_ids"]
    async with factory() as db:
        for tid, week in ((t1, 1), (t2, 2)):
            (await db.execute(select(Team).where(Team.id == tid))).scalar_one().eliminated_week = week
        await db.commit()

    # Weeks 1-2: t4 tops the league, t3 is just above the cut. Finale
    # weeks 3-18 (16 games): t3 takes the series 7-6 with 3 ties, while
    # t4 scores more overall and ends with more total wins.
    weeks = {1: {t1: 10, t2: 50, t3: 40, t4: 200}, 2: {t2: 10, t3: 40, t4: 200}}
    results = ["t3"] * 7 + ["t4"] * 6 + ["tie"] * 3
    for i, r in enumerate(results):
        weeks[3 + i] = {t3: 101, t4: 100} if r == "t3" else {t3: 50, t4: 160} if r == "t4" else {t3: 90, t4: 90}
    await _seed_scores(factory, league_id, weeks)

    async with factory() as db:
        rows, summary = await get_standings_detail(league_id, db)
        plain = await get_standings(league_id, db)

    by_id = {r["team_id"]: r for r in rows}
    assert by_id[t4]["wins"] > by_id[t3]["wins"]
    assert by_id[t4]["points_for"] > by_id[t3]["points_for"]
    assert summary["champion_team_id"] == t3
    assert summary["finalists"][0]["team_id"] == t3
    assert (summary["finalists"][0]["wins"], summary["finalists"][0]["losses"],
            summary["finalists"][0]["ties"]) == (7, 6, 3)
    assert summary["finale_weeks"] == list(range(3, 19))
    assert [r["team_id"] for r in rows] == [t3, t4, t2, t1]
    assert [r["guillotine_place"] for r in rows] == [1, 2, 3, 4]
    assert [r["team_id"] for r in plain] == [t3, t4, t2, t1]


@pytest.mark.asyncio
async def test_non_guillotine_league_has_no_summary(seed):
    async with seed["db_session_factory"]() as db:
        rows, summary = await get_standings_detail(seed["league_id"], db)
    assert summary is None
    assert all("guillotine_place" not in r for r in rows)


@pytest.mark.asyncio
async def test_standings_endpoint_returns_the_summary(client, guillotine_seed):
    r = await client.get(f"/leagues/{guillotine_seed['league_id']}/standings",
                         headers={"Authorization": f"Bearer {guillotine_seed['token']}"})
    assert r.status_code == 200
    g = r.json()["guillotine"]
    assert g["phase"] == "elimination"
    assert g["champion_team_id"] is None
