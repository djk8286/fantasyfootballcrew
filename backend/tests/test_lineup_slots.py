"""Slot lineups: placing starters into the league's slots, position checks,
per-player kickoff locks, and the warnings PUT /lineup returns."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.league import DraftStatus, League, LeagueType
from app.models.lineup import Lineup
from app.models.nfl_game import NFLGame
from app.models.player import Player
from app.models.team import Team
from app.models.user import User
from app.services.auth_service import create_access_token
from app.services.lineup_slots import LineupError, PlayerState, lineup_issues, place_starters, validate_slots

YEAR, WEEK = 2026, 7
STANDARD = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SUPERFLEX": 0, "K": 1, "DEF": 1}


def _ids(slots):
    return [(s["slot"], s["player_id"]) for s in slots]


# ─── Placing starters ───────────────────────────────────────────────────

POS = {"qb1": "QB", "qb2": "QB", "rb1": "RB", "rb2": "RB", "rb3": "RB", "wr1": "WR", "wr2": "WR",
       "te1": "TE", "k1": "K", "d1": "DEF", "dl1": "DL", "dl2": "DL"}


def test_each_starter_goes_to_his_own_slot_and_the_extra_rb_to_flex():
    slots, left = place_starters(["rb3", "rb1", "rb2", "qb1", "wr1", "wr2", "te1", "k1", "d1"], POS, STANDARD)
    assert left == []
    assert _ids(slots) == [("QB", "qb1"), ("RB", "rb3"), ("RB", "rb1"), ("WR", "wr1"), ("WR", "wr2"),
                           ("TE", "te1"), ("FLEX", "rb2"), ("K", "k1"), ("DEF", "d1")]


def test_second_qb_does_not_fit_without_superflex():
    slots, left = place_starters(["qb1", "qb2", "rb1"], POS, STANDARD)
    assert left == ["qb2"]
    assert ("FLEX", None) in _ids(slots)


def test_qb_gets_superflex_even_when_a_skill_player_is_listed_first():
    league = {**STANDARD, "FLEX": 0, "SUPERFLEX": 1}
    slots, left = place_starters(["rb1", "rb2", "rb3", "qb1", "qb2"], POS, league)
    assert left == ["rb3"]
    assert ("SUPERFLEX", "qb2") in _ids(slots)


def test_extra_dl_goes_to_idp_flex():
    slots, left = place_starters(["dl1", "dl2"], POS, {"DL": 1, "IDP_FLEX": 1})
    assert left == [] and _ids(slots) == [("DL", "dl1"), ("IDP_FLEX", "dl2")]


def test_empty_slots_stay_empty():
    slots, _ = place_starters(["qb1"], POS, STANDARD)
    assert sum(1 for s in slots if s["player_id"] is None) == 8


# ─── Validating client slots ────────────────────────────────────────────

@pytest.mark.parametrize("submitted, message", [
    ([{"slot": "FLEX", "player_id": "qb1"}], "can't play FLEX"),
    ([{"slot": "RB", "player_id": "wr1"}], "can't play RB"),
    ([{"slot": "QB", "player_id": "qb1"}, {"slot": "QB", "player_id": "qb2"}], "no open QB slot"),
    ([{"slot": "RB", "player_id": "rb1"}, {"slot": "FLEX", "player_id": "rb1"}], "in two slots"),
    ([{"slot": "QB", "player_id": "stranger"}], "isn't on this roster"),
    ([{"slot": "SUPERFLEX", "player_id": "qb1"}], "no open SUPERFLEX slot"),
])
def test_illegal_slot_assignments_are_rejected(submitted, message):
    with pytest.raises(LineupError, match=message):
        validate_slots(submitted, POS, {}, STANDARD)


def test_valid_slots_come_back_in_league_order_with_empties():
    slots = validate_slots([{"slot": "FLEX", "player_id": "wr2"}, {"slot": "QB", "player_id": "qb1"}], POS, {}, STANDARD)
    assert slots[0] == {"slot": "QB", "player_id": "qb1"}
    assert slots[6] == {"slot": "FLEX", "player_id": "wr2"}
    assert len(slots) == 9


def test_issues_name_empty_slots_out_and_bye_starters():
    slots = [{"slot": "QB", "player_id": "a"}, {"slot": "RB", "player_id": "b"}, {"slot": "WR", "player_id": None}]
    players = {"a": PlayerState("Al Out", "Out", True, False), "b": PlayerState("Bo Bye", None, False, True)}
    issues = lineup_issues(slots, players, unplaced=["a"])
    assert [(i["kind"], i["slot"]) for i in issues] == [("out", "QB"), ("bye", "RB"), ("empty", "WR"), ("illegal", None)]
    assert issues[0]["message"] == "Al Out is listed Out and may not play."
    assert issues[1]["message"] == "Bo Bye is on bye and won't score."


# ─── Endpoints ──────────────────────────────────────────────────────────

ROSTER = [  # label, position, nfl team, injury
    ("QB1", "QB", "KC", None), ("QB2", "QB", "SF", None),
    ("RB1", "RB", "KC", None), ("RB2", "RB", "SF", None), ("RB3", "RB", "LAC", None),
    ("WR1", "WR", "KC", None), ("WR2", "WR", "SF", None), ("WR3", "WR", "KC", "Out"),
    ("TE1", "TE", "KC", None), ("K1", "K", "SF", None), ("DEF1", "DEF", "KC", None),
]


def _game(home, away, kickoff, state="pre"):
    return NFLGame(id=str(uuid.uuid4()), espn_event_id=str(uuid.uuid4()), week=WEEK, year=YEAR, season_type=2,
                   home_team=home, home_team_name=home, away_team=away, away_team_name=away,
                   status_state=state, status_detail="", completed=state == "post", kickoff_at=kickoff)


async def _seed(db_session_factory, *, sf_started=False, legacy_starters=None):
    """KC plays later this week; SF has kicked off if sf_started; LAC is on bye."""
    now = datetime.now(timezone.utc)
    async with db_session_factory() as db:
        owner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local", username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        league = League(id=str(uuid.uuid4()), name="L", commissioner_id=owner.id, league_type=LeagueType.STANDARD,
                        draft_status=DraftStatus.COMPLETED, scoring_config={"generic": {"pts": 1.0}}, roster_slots={})
        db.add_all([owner, league])
        await db.flush()
        ids = {}
        for i, (label, pos, nfl, injury) in enumerate(ROSTER):
            p = Player(id=f"{i:02d}-{label}", sleeper_id=f"s-{label}-{uuid.uuid4().hex[:6]}", first_name=label, last_name="X",
                       position=pos, team=nfl, injury_status=injury, stats_year=YEAR,
                       week_stats={"1": {"pts": 100 - i}})
            db.add(p)
            ids[label] = p.id
        team = Team(id=str(uuid.uuid4()), name="T", league_id=league.id, owner_id=owner.id, roster=list(ids.values()), roster_version=0)
        db.add(team)
        db.add_all([
            _game("KC", "LV", now + timedelta(days=3)),
            _game("SF", "SEA", now - timedelta(minutes=30) if sf_started else now + timedelta(days=1),
                  state="in" if sf_started else "pre"),
        ])
        if legacy_starters is not None:
            db.add(Lineup(team_id=team.id, week=WEEK, year=YEAR, starters=[ids[l] for l in legacy_starters]))
        await db.commit()
        token = create_access_token({"sub": owner.id, "email": owner.email})
        return {"team": team.id, "ids": ids, "auth": {"Authorization": f"Bearer {token}"}}


PARAMS = {"week": WEEK, "year": YEAR}
FULL = [("QB", "QB1"), ("RB", "RB1"), ("RB", "RB2"), ("WR", "WR1"), ("WR", "WR2"), ("TE", "TE1"),
        ("FLEX", "RB3"), ("K", "K1"), ("DEF", "DEF1")]


def _slots(s, pairs):
    return [{"slot": slot, "player_id": s["ids"][label] if label else None} for slot, label in pairs]


def _labels(s, slots):
    back = {v: k for k, v in s["ids"].items()}
    return [(e["slot"], back.get(e["player_id"])) for e in slots]


async def _get(client, s):
    r = await client.get(f"/teams/{s['team']}/lineup", params=PARAMS, headers=s["auth"])
    assert r.status_code == 200
    return r.json()


async def _put(client, s, **body):
    return await client.put(f"/teams/{s['team']}/lineup", params=PARAMS, json=body, headers=s["auth"])


@pytest.mark.asyncio
async def test_saved_slots_round_trip_and_keep_starters_in_sync(client, db_session_factory):
    s = await _seed(db_session_factory)
    r = await _put(client, s, slots=_slots(s, FULL))
    assert r.status_code == 200, r.text
    body = await _get(client, s)
    assert _labels(s, body["slots"]) == FULL
    assert set(body["starters"]) == {s["ids"][l] for _, l in FULL}
    async with db_session_factory() as db:
        row = (await db.execute(select(Lineup).where(Lineup.team_id == s["team"]))).scalar_one()
        assert set(row.starters) == {s["ids"][l] for _, l in FULL}


@pytest.mark.asyncio
async def test_put_rejects_a_qb_in_flex(client, db_session_factory):
    s = await _seed(db_session_factory)
    r = await _put(client, s, slots=_slots(s, [("FLEX", "QB2")]))
    assert r.status_code == 422
    assert "QB2 X (QB) can't play FLEX" in r.json()["detail"]


@pytest.mark.asyncio
async def test_old_starters_list_is_placed_into_slots_and_two_qbs_are_rejected(client, db_session_factory):
    s = await _seed(db_session_factory)
    ok = await _put(client, s, starters=[s["ids"][l] for _, l in FULL])
    assert ok.status_code == 200
    assert _labels(s, ok.json()["slots"]) == FULL

    bad = await _put(client, s, starters=[s["ids"]["QB1"], s["ids"]["QB2"], s["ids"]["RB1"]])
    assert bad.status_code == 422
    assert bad.json()["detail"] == "No open starting slot for QB2 X (QB)."


@pytest.mark.asyncio
async def test_starting_an_out_or_bye_player_saves_with_a_warning(client, db_session_factory):
    s = await _seed(db_session_factory)
    pairs = [(slot, "WR3" if label == "WR2" else label) for slot, label in FULL]  # WR3 is Out, RB3 (LAC) is on bye
    r = await _put(client, s, slots=_slots(s, pairs))
    assert r.status_code == 200
    body = r.json()
    assert sorted(i["kind"] for i in body["issues"]) == ["bye", "out"]
    assert "WR3 X is listed Out and may not play." in body["warnings"]
    assert "RB3 X is on bye and won't score." in body["warnings"]


@pytest.mark.asyncio
async def test_locked_player_cannot_be_benched_or_started(client, db_session_factory):
    s = await _seed(db_session_factory, legacy_starters=[l for _, l in FULL])
    async with db_session_factory() as db:
        game = (await db.execute(select(NFLGame).where(NFLGame.home_team == "SF"))).scalar_one()
        game.status_state, game.kickoff_at = "in", datetime.now(timezone.utc) - timedelta(minutes=10)
        await db.commit()

    bench_rb2 = [(slot, None if label == "RB2" else label) for slot, label in FULL]  # RB2 plays for SF
    r = await _put(client, s, slots=_slots(s, bench_rb2))
    assert r.status_code == 409
    assert r.json()["detail"] == "Locked at kickoff, can't be moved: RB2 X."

    start_qb2 = [("QB", "QB2")] + FULL[1:]  # QB2 (SF, locked) in for QB1
    r = await _put(client, s, slots=_slots(s, start_qb2))
    assert r.status_code == 409
    assert "QB2 X" in r.json()["detail"]

    swap_unlocked = [(slot, "WR3" if label == "WR1" else label) for slot, label in FULL]  # both KC, not started
    r = await _put(client, s, slots=_slots(s, swap_unlocked))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_without_saved_lineup_shows_default_in_slots(client, db_session_factory):
    s = await _seed(db_session_factory)
    body = await _get(client, s)
    assert body["has_lineup_set"] is False
    placed = {pid for pid in (e["player_id"] for e in body["slots"]) if pid}
    assert placed == set(body["default_starters"])
    # LAC is on bye and WR3 is Out, so neither is in the default.
    assert s["ids"]["RB3"] not in placed and s["ids"]["WR3"] not in placed


@pytest.mark.asyncio
async def test_legacy_lineup_that_fits_no_slot_is_flagged(client, db_session_factory):
    s = await _seed(db_session_factory, legacy_starters=["QB1", "QB2", "RB1"])
    body = await _get(client, s)
    assert body["unplaced"] == [s["ids"]["QB2"]]
    kinds = [i["kind"] for i in body["issues"]]
    assert "illegal" in kinds and kinds.count("empty") == 7


@pytest.mark.asyncio
async def test_optimize_keeps_locked_starters_and_skips_out_and_bye(client, db_session_factory):
    s = await _seed(db_session_factory, sf_started=True, legacy_starters=["QB2", "RB1"])
    r = await client.post(f"/teams/{s['team']}/lineup/optimize", params=PARAMS, headers=s["auth"])
    assert r.status_code == 200, r.text
    body = r.json()
    starters = {l for _, l in _labels(s, body["slots"]) if l}
    assert "QB2" in starters                                  # locked starter kept
    assert not starters & {"RB2", "WR2", "K1"}                # locked bench players stay benched
    assert not starters & {"RB3", "WR3"}                      # bye, Out
    assert body["kept_locked"] == ["QB2 X"]
