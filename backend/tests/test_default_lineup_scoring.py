"""Default lineups for teams with no saved Lineup (redesign PR 1).

Before: a team with no Lineup row for a week scored its WHOLE roster,
so every CPU team counted 15 players (2 QBs, 2 Ks...) against a human
capped at 9 starters. Now it scores a legal default lineup built from
the league's roster slots, ranked only by stats from earlier weeks.

Scores are controlled exactly with a generic scoring category
({"generic": {"pts": 1.0}}, stats {"pts": n}), same trick as
test_best_ball_scoring.py.
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.league import League, LeagueType, DraftStatus
from app.models.lineup import Lineup
from app.models.nfl_game import NFLGame
from app.models.player import Player
from app.models.team import Team
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token
from app.services.default_lineup import (
    Candidate,
    choose_default_starters,
    pre_week_ranking_stats,
)
from app.services.scoring_engine import DEFAULT_ROSTER_SLOTS
from app.services.standings_service import calculate_week, get_standings, repair_default_lineup_scores

YEAR = 2026
WEEK = 3
GENERIC = {"generic": {"pts": 1.0}}
SLOTS = dict(DEFAULT_ROSTER_SLOTS)  # QB1 RB2 WR2 TE1 FLEX1 K1 DEF1 = 9


def C(pid, pos, pts, team="KC", injury=None):
    return Candidate(player_id=pid, position=pos, nfl_team=team, injury_status=injury, ranking_stats={"pts": pts})


# ─── Pure selection rules ───────────────────────────────────────────────

FULL_POOL = [
    C("qb1", "QB", 30), C("qb2", "QB", 25),
    C("rb1", "RB", 20), C("rb2", "RB", 18), C("rb3", "RB", 9),
    C("wr1", "WR", 19), C("wr2", "WR", 17), C("wr3", "WR", 12),
    C("te1", "TE", 10), C("te2", "TE", 4),
    C("k1", "K", 8), C("k2", "K", 7),
    C("def1", "DEF", 6),
]


def _positions(starters, pool):
    by_id = {c.player_id: c.position for c in pool}
    return sorted(by_id[s] for s in starters)


def test_fills_every_slot_legally_and_benches_extra_qb_and_k():
    starters = choose_default_starters(FULL_POOL, SLOTS, GENERIC)
    assert len(starters) == 9
    assert _positions(starters, FULL_POOL) == sorted(["QB", "RB", "RB", "WR", "WR", "TE", "WR", "K", "DEF"])
    assert "qb2" not in starters and "k2" not in starters
    # FLEX takes the best remaining RB/WR/TE (wr3=12) -- never the
    # higher-ranked backup QB (25), which isn't FLEX-eligible.
    assert "wr3" in starters and "rb3" not in starters


def test_superflex_slot_can_take_the_backup_qb():
    slots = {**SLOTS, "SUPERFLEX": 1}
    starters = choose_default_starters(FULL_POOL, slots, GENERIC)
    assert "qb2" in starters and len(starters) == 10


def test_missing_position_leaves_the_slot_empty():
    pool = [c for c in FULL_POOL if c.position != "DEF"]
    starters = choose_default_starters(pool, SLOTS, GENERIC)
    assert len(starters) == 8
    assert "DEF" not in _positions(starters, pool)


def test_bye_week_players_are_skipped_when_schedule_known():
    pool = [C("def_bye", "DEF", 50, team="LAC"), C("wr_bye", "WR", 99, team="LAC")] + [c for c in FULL_POOL if c.position != "DEF"]
    starters = choose_default_starters(pool, SLOTS, GENERIC, teams_playing={"KC"})
    assert "def_bye" not in starters and "wr_bye" not in starters
    assert len(starters) == 8  # DEF slot empty: only DEF is on bye
    # Unknown schedule: nobody is treated as on bye.
    assert "wr_bye" in choose_default_starters(pool, SLOTS, GENERIC, teams_playing=None)


def test_inactive_players_skipped_only_when_asked():
    pool = [C("qb_out", "QB", 99, injury="Out")] + FULL_POOL
    assert "qb_out" not in choose_default_starters(pool, SLOTS, GENERIC, exclude_inactive=True)
    assert "qb_out" in choose_default_starters(pool, SLOTS, GENERIC, exclude_inactive=False)
    q = [C("qb_q", "QB", 99, injury="Questionable")] + FULL_POOL
    assert "qb_q" in choose_default_starters(q, SLOTS, GENERIC, exclude_inactive=True)


def test_ties_break_by_player_id_regardless_of_input_order():
    pool = [C(f"rb{i}", "RB", 10) for i in range(6)] + [C("qb", "QB", 1)]
    expected = choose_default_starters(pool, SLOTS, GENERIC)
    for seed in range(5):
        shuffled = pool[:]
        random.Random(seed).shuffle(shuffled)
        assert choose_default_starters(shuffled, SLOTS, GENERIC) == expected
    assert [s for s in expected if s.startswith("rb")] == ["rb0", "rb1", "rb2"]  # RB, RB, FLEX


class _P:
    def __init__(self, week_stats, stats_year=YEAR, last=None):
        self.week_stats, self.stats_year, self.last_season_stats = week_stats, stats_year, last


def test_ranking_uses_only_weeks_before_the_scored_week():
    p = _P({"1": {"pts": 5}, "2": {"pts": 7}, "3": {"pts": 100}, "4": {"pts": 100}})
    assert pre_week_ranking_stats(p, 3, YEAR) == {"pts": 12}


def test_ranking_falls_back_to_last_season():
    assert pre_week_ranking_stats(_P({"3": {"pts": 9}}, last={"pts": 40}), 1, YEAR) == {"pts": 40}
    assert pre_week_ranking_stats(_P({"1": {"pts": 9}}, stats_year=YEAR - 1, last={"pts": 40}), 3, YEAR) == {"pts": 40}
    assert pre_week_ranking_stats(_P({}, last=None), 3, YEAR) == {}


# ─── calculate_week integration ─────────────────────────────────────────

# label, position, nfl team, points in earlier weeks (ranking), points THIS week
ROSTER = [
    ("QB1", "QB", "KC", 30, 10), ("QB2", "QB", "KC", 20, 40),
    ("RB1", "RB", "KC", 25, 12), ("RB2", "RB", "KC", 22, 11), ("RB3", "RB", "KC", 5, 50),
    ("WR1", "WR", "KC", 24, 9), ("WR2", "WR", "KC", 21, 8), ("WR3", "WR", "KC", 15, 7),
    ("TE1", "TE", "KC", 14, 6), ("TE2", "TE", "KC", 3, 30),
    ("K1", "K", "KC", 10, 5), ("K2", "K", "KC", 2, 20),
    ("DEF1", "DEF", "LAC", 9, 4),
]
DEFAULT_LABELS = {"QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "WR3", "K1", "DEF1"}


async def _league(db_session_factory, *, cpu_b=True, games=None):
    """Two-team league (human team A vs team B, CPU by default), both with
    the ROSTER above (separate Player rows each). Returns ids and the
    week-scoring stats payload."""
    async with db_session_factory() as db:
        owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(owner)
        league = League(id=str(uuid.uuid4()), name="Default Lineup League", commissioner_id=owner.id,
                        league_type=LeagueType.STANDARD, draft_status=DraftStatus.COMPLETED,
                        scoring_config=GENERIC, roster_slots={})
        db.add(league)
        await db.flush()
        stats, labels = {}, {}
        teams = []
        for name, is_cpu in (("A", False), ("B", cpu_b)):
            ids = []
            for label, pos, nfl, hist, now in ROSTER:
                p = Player(id=str(uuid.uuid4()), sleeper_id=f"s-{name}-{label}-{uuid.uuid4().hex[:6]}",
                           first_name=label, last_name=name, position=pos, team=nfl,
                           stats_year=YEAR, week_stats={"1": {"pts": hist}})
                db.add(p)
                stats[p.sleeper_id] = {"pts": now}
                labels[p.id] = label
                ids.append(p.id)
            t = Team(id=str(uuid.uuid4()), name=f"Team {name}", league_id=league.id,
                     owner_id=None if is_cpu else owner.id, is_cpu=is_cpu, roster=ids, roster_version=0)
            db.add(t)
            teams.append(t)
        for g in games or []:
            db.add(g)
        await db.commit()
        token = create_access_token({"sub": owner.id, "email": owner.email})
        return {"league": league.id, "a": teams[0].id, "b": teams[1].id, "stats": stats, "labels": labels, "token": token}


def _game(home, away, kickoff, state="pre", completed=False, week=WEEK):
    return NFLGame(id=str(uuid.uuid4()), espn_event_id=str(uuid.uuid4()), week=week, year=YEAR, season_type=2,
                   home_team=home, home_team_name=home, away_team=away, away_team_name=away,
                   status_state=state, status_detail="", completed=completed, kickoff_at=kickoff)


async def _ws(db_session_factory, league_id, team_id):
    async with db_session_factory() as db:
        return (await db.execute(select(WeeklyScore).where(
            WeeklyScore.league_id == league_id, WeeklyScore.team_id == team_id,
            WeeklyScore.week == WEEK, WeeklyScore.year == YEAR))).scalar_one()


async def _lineup_row(db_session_factory, team_id):
    async with db_session_factory() as db:
        return (await db.execute(select(Lineup).where(Lineup.team_id == team_id, Lineup.week == WEEK, Lineup.year == YEAR))).scalar_one_or_none()


def _week_points(labels_subset):
    now = {label: n for label, _, _, _, n in ROSTER}
    return float(sum(now[l] for l in labels_subset))


@pytest.mark.asyncio
async def test_missing_lineup_scores_default_starters_only(db_session_factory):
    s = await _league(db_session_factory)
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    for team in ("a", "b"):
        ws = await _ws(db_session_factory, s["league"], s[team])
        starters = {s["labels"][pid] for pid in ws.lineup_data["default_starters"]}
        # Ranked on earlier weeks: QB2/RB3/TE2/K2 had big weeks but stay
        # benched -- no hindsight.
        assert starters == DEFAULT_LABELS
        assert ws.total_score == _week_points(DEFAULT_LABELS)
        assert ws.total_score < _week_points([r[0] for r in ROSTER])  # not the whole roster
        bench = {s["labels"][pid] for pid, e in ws.lineup_data["breakdown"].items() if e["is_bench"]}
        assert bench == {"QB2", "RB3", "TE2", "K2"}
        assert ws.lineup_data["lineup_source"] == "default"


@pytest.mark.asyncio
async def test_saved_lineup_still_wins_over_default(db_session_factory):
    s = await _league(db_session_factory)
    async with db_session_factory() as db:
        team_a = (await db.execute(select(Team).where(Team.id == s["a"]))).scalar_one()
        qb2 = next(pid for pid in team_a.roster if s["labels"][pid] == "QB2")
        db.add(Lineup(team_id=s["a"], week=WEEK, year=YEAR, starters=[qb2]))
        await db.commit()
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    ws = await _ws(db_session_factory, s["league"], s["a"])
    assert ws.total_score == 40.0
    assert ws.lineup_data["lineup_source"] == "saved"
    assert "default_starters" not in ws.lineup_data


@pytest.mark.asyncio
async def test_cpu_team_saves_lineup_once_week_started_human_does_not(db_session_factory):
    started = datetime.now(timezone.utc) - timedelta(hours=1)
    s = await _league(db_session_factory, games=[_game("KC", "LAC", started, state="in")])
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    cpu_lineup = await _lineup_row(db_session_factory, s["b"])
    assert cpu_lineup is not None
    assert {s["labels"][pid] for pid in cpu_lineup.starters} == DEFAULT_LABELS
    assert await _lineup_row(db_session_factory, s["a"]) is None
    # Second run reads the CPU's saved row; score unchanged.
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    ws = await _ws(db_session_factory, s["league"], s["b"])
    assert ws.lineup_data["lineup_source"] == "saved"
    assert ws.total_score == _week_points(DEFAULT_LABELS)


@pytest.mark.asyncio
async def test_default_reacts_to_injury_before_kickoff_then_freezes(db_session_factory):
    future = datetime.now(timezone.utc) + timedelta(days=2)
    s = await _league(db_session_factory, games=[_game("KC", "LAC", future)])
    async with db_session_factory() as db:
        team_a = (await db.execute(select(Team).where(Team.id == s["a"]))).scalar_one()
        qb1 = next(pid for pid in team_a.roster if s["labels"][pid] == "QB1")
        (await db.get(Player, qb1)).injury_status = "Out"
        await db.commit()
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    ws = await _ws(db_session_factory, s["league"], s["a"])
    first = ws.lineup_data["default_starters"]
    assert qb1 not in first and "QB2" in {s["labels"][p] for p in first}
    assert await _lineup_row(db_session_factory, s["b"]) is None  # not started: CPU not saved yet

    # Kickoff passes; QB1 is suddenly cleared. The frozen default stays.
    async with db_session_factory() as db:
        game = (await db.execute(select(NFLGame))).scalar_one()
        game.kickoff_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        game.status_state = "in"
        (await db.get(Player, qb1)).injury_status = None
        await db.commit()
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    ws = await _ws(db_session_factory, s["league"], s["a"])
    assert ws.lineup_data["default_starters"] == first


@pytest.mark.asyncio
async def test_bye_week_from_schedule_leaves_def_slot_empty(db_session_factory):
    # DEF1 plays for LAC, which has no game this week.
    s = await _league(db_session_factory, games=[_game("KC", "DEN", datetime.now(timezone.utc) - timedelta(hours=3), state="post", completed=True)])
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    ws = await _ws(db_session_factory, s["league"], s["a"])
    starters = {s["labels"][pid] for pid in ws.lineup_data["default_starters"]}
    assert starters == DEFAULT_LABELS - {"DEF1"}
    assert ws.total_score == _week_points(DEFAULT_LABELS - {"DEF1"})


@pytest.mark.asyncio
async def test_lineup_endpoint_shows_default_starters(client, db_session_factory):
    s = await _league(db_session_factory)
    r = await client.get(f"/teams/{s['a']}/lineup", params={"week": WEEK, "year": YEAR})
    assert r.status_code == 200
    body = r.json()
    assert body["has_lineup_set"] is False
    assert {s["labels"][pid] for pid in body["default_starters"]} == DEFAULT_LABELS


# ─── Repair of weeks scored under the old rule ──────────────────────────

async def _old_style_rows(db_session_factory, s, team_a_saved=False):
    """WeeklyScore rows exactly as the old code wrote them: no
    lineup_source, every player is_bench False, total = whole roster."""
    async with db_session_factory() as db:
        for key in ("a", "b"):
            team = (await db.execute(select(Team).where(Team.id == s[key]))).scalar_one()
            players = {p.id: p for p in (await db.execute(select(Player).where(Player.id.in_(team.roster)))).scalars().all()}
            if key == "a" and team_a_saved:
                starters = [pid for pid in team.roster if s["labels"][pid] in {"QB1", "RB1"}]
                db.add(Lineup(team_id=team.id, week=WEEK, year=YEAR, starters=starters))
                scored = starters
            else:
                scored = list(team.roster)
            breakdown = {pid: {"score": s["stats"][players[pid].sleeper_id]["pts"], "stats": {}, "position": players[pid].position,
                               "is_bench": pid not in scored} for pid in team.roster}
            total = float(sum(breakdown[pid]["score"] for pid in scored))
            db.add(WeeklyScore(league_id=s["league"], team_id=team.id, week=WEEK, year=YEAR, total_score=total,
                               lineup_data={"total": total, "breakdown": breakdown}))
        await db.commit()


@pytest.mark.asyncio
async def test_repair_rescores_whole_roster_weeks_and_flips_the_result(db_session_factory):
    s = await _league(db_session_factory)
    await _old_style_rows(db_session_factory, s, team_a_saved=True)
    # Old: A (saved QB1+RB1) = 22, B (CPU, whole roster) = 212 -> B won.
    async with db_session_factory() as db:
        before = {r["team_id"]: r for r in await get_standings(s["league"], db)}
    assert before[s["b"]]["wins"] == 1 and before[s["a"]]["losses"] == 1

    async with db_session_factory() as db:
        changes = await repair_default_lineup_scores(db)
    assert [(c["team_id"], c["old_total"], c["new_total"]) for c in changes] == [
        (s["b"], _week_points([r[0] for r in ROSTER]), _week_points(DEFAULT_LABELS))
    ]
    ws_a = await _ws(db_session_factory, s["league"], s["a"])
    ws_b = await _ws(db_session_factory, s["league"], s["b"])
    assert ws_a.total_score == 22.0 and ws_a.lineup_data["lineup_source"] == "saved"
    assert ws_b.lineup_data["lineup_source"] == "default"
    assert {s["labels"][p] for p in ws_b.lineup_data["default_starters"]} == DEFAULT_LABELS
    assert {s["labels"][p] for p, e in ws_b.lineup_data["breakdown"].items() if e["is_bench"]} == {"QB2", "RB3", "TE2", "K2"}

    # Idempotent: a second pass finds nothing to do.
    async with db_session_factory() as db:
        assert await repair_default_lineup_scores(db) == []
    assert (await _ws(db_session_factory, s["league"], s["b"])).total_score == _week_points(DEFAULT_LABELS)


@pytest.mark.asyncio
async def test_repair_can_flip_winner(db_session_factory):
    """Human A saved a lineup worth more than B's default lineup but less
    than B's whole roster: the old rule handed B the win."""
    s = await _league(db_session_factory)
    async with db_session_factory() as db:
        team_a = (await db.execute(select(Team).where(Team.id == s["a"]))).scalar_one()
        players = {p.id: p for p in (await db.execute(select(Player).where(Player.id.in_(team_a.roster)))).scalars().all()}
        starters = [pid for pid in team_a.roster if s["labels"][pid] in {"QB2", "RB3", "TE2", "K2", "RB1"}]  # 40+50+30+20+12=152
        db.add(Lineup(team_id=team_a.id, week=WEEK, year=YEAR, starters=starters))
        bd = {pid: {"score": s["stats"][players[pid].sleeper_id]["pts"], "position": players[pid].position, "is_bench": pid not in starters} for pid in team_a.roster}
        db.add(WeeklyScore(league_id=s["league"], team_id=team_a.id, week=WEEK, year=YEAR, total_score=152.0, lineup_data={"total": 152.0, "breakdown": bd}))
        team_b = (await db.execute(select(Team).where(Team.id == s["b"]))).scalar_one()
        pb = {p.id: p for p in (await db.execute(select(Player).where(Player.id.in_(team_b.roster)))).scalars().all()}
        bdb = {pid: {"score": s["stats"][pb[pid].sleeper_id]["pts"], "position": pb[pid].position, "is_bench": False} for pid in team_b.roster}
        whole = float(sum(e["score"] for e in bdb.values()))
        db.add(WeeklyScore(league_id=s["league"], team_id=team_b.id, week=WEEK, year=YEAR, total_score=whole, lineup_data={"total": whole, "breakdown": bdb}))
        await db.commit()
    async with db_session_factory() as db:
        before = {r["team_id"]: r for r in await get_standings(s["league"], db)}
    assert before[s["b"]]["wins"] == 1
    async with db_session_factory() as db:
        await repair_default_lineup_scores(db)
    async with db_session_factory() as db:
        after = {r["team_id"]: r for r in await get_standings(s["league"], db)}
    assert after[s["a"]]["wins"] == 1 and after[s["b"]]["losses"] == 1
    assert after[s["b"]]["points_for"] == _week_points(DEFAULT_LABELS)


@pytest.mark.asyncio
async def test_repair_skips_rows_scored_under_new_rules(db_session_factory):
    s = await _league(db_session_factory)
    async with db_session_factory() as db:
        await calculate_week(s["league"], WEEK, YEAR, db, sleeper_stats=s["stats"])
    async with db_session_factory() as db:
        assert await repair_default_lineup_scores(db) == []
