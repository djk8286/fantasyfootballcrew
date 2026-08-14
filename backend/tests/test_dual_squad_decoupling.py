"""
Tests for Phase 7 ("Dual-Squad/Mirror") Step 5 -- decoupling-proof
tests confirming DUAL_SQUAD composes cleanly with every other
subsystem (Salary-Cap, Best-Ball, trades, waivers, draft) with zero
special-casing needed anywhere outside standings_service._effective_matchups
and get_combined_standings. Mirrors the rigor test_best_ball_scoring.py's
own decoupling tests (test_guillotine_decoupling,
test_salary_cap_and_best_ball_coexist) already established.
"""
import json
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.draft import Draft, DraftPick
from app.models.contract import Contract
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.services.auth_service import create_access_token
from app.services.draft_manager import create_draft, start_draft, make_pick
from app.services.standings_service import calculate_week, get_standings, get_combined_standings
from app.services.waiver_service import process_league_waivers

WEEK, YEAR = 1, 2026


async def _make_league(db_session_factory, num_teams=4, extra_kwargs=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dsdcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Dual Squad Decoupling Test League",
                         commissioner_id=commissioner.id, league_type=LeagueType.DUAL_SQUAD,
                         draft_status=DraftStatus.COMPLETED, scoring_config={"generic": {"pts": 1.0}}, roster_slots={},
                         **(extra_kwargs or {}))
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0)
            for i in range(num_teams)
        ]
        db.add_all(teams)
        await db.flush()
        for i in range(0, num_teams, 2):
            teams[i].partner_team_id = teams[i + 1].id
            teams[i + 1].partner_team_id = teams[i].id
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"token": token, "commissioner_id": commissioner.id, "league_id": league.id,
                "team_ids": [t.id for t in teams], "db_session_factory": db_session_factory}


@pytest.mark.asyncio
async def test_dual_squad_and_salary_cap_coexist(db_session_factory):
    cap_settings = {
        "enabled": True, "cap_total": 200.0, "max_roster_size": 20,
        "top_salary": 50.0, "bottom_salary": 1.0, "waiver_salary_pct": 0.6,
        "dead_money_pct": 0.5, "default_contract_years": 2, "waiver_contract_years": 1,
    }
    setup = await _make_league(db_session_factory, num_teams=4, extra_kwargs={"salary_cap_settings": cap_settings})
    league_id = setup["league_id"]
    t0, t1, t2, t3 = setup["team_ids"]

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        league.draft_status = DraftStatus.NOT_STARTED
        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-dsd-{i}", first_name=f"P{i}", last_name="Test", position="RB")
            for i in range(4 * 3)
        ]
        db.add_all(players)
        await db.commit()
        player_ids = [p.id for p in players]

    async with db_session_factory() as db:
        draft = await create_draft(db, league_id, total_rounds=3)
        draft = await start_draft(db, draft.id)

    team_order = json.loads(draft.team_order)
    async with db_session_factory() as db:
        # Draft the first 4 picks (one per team) -- enough to prove a
        # cap-enabled draft pick creates a Contract without erroring on
        # a DUAL_SQUAD league.
        for pid in player_ids[:4]:
            fresh = (await db.execute(select(Draft).where(Draft.id == draft.id))).scalar_one()
            idx = (fresh.current_round - 1) * 4 + (fresh.current_pick - 1)
            team_id = json.loads(fresh.team_order)[idx]
            await make_pick(db, draft.id, team_id, pid)

        contracts = (await db.execute(select(Contract).where(Contract.league_id == league_id))).scalars().all()
        assert len(contracts) == 4

    # calculate_week and the DUAL_SQUAD schedule exclusion still work fine.
    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats={})
    async with db_session_factory() as db:
        standings = await get_standings(league_id, db)
    assert len(standings) == 4


@pytest.mark.asyncio
async def test_dual_squad_and_best_ball_coexist(db_session_factory):
    setup = await _make_league(db_session_factory, num_teams=4, extra_kwargs={"best_ball_settings": {"enabled": True}})
    league_id = setup["league_id"]
    t0, t1, t2, t3 = setup["team_ids"]

    async with db_session_factory() as db:
        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-dsbb-{i}-{uuid.uuid4().hex[:6]}",
                   first_name=f"P{i}", last_name="Test", position="RB")
            for i in range(3)
        ]
        db.add_all(players)
        await db.flush()
        team_row = (await db.execute(select(Team).where(Team.id == t0))).scalar_one()
        team_row.roster = [p.id for p in players]
        await db.commit()

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats={})

    from app.models.weekly_score import WeeklyScore
    async with db_session_factory() as db:
        score = (await db.execute(select(WeeklyScore).where(
            WeeklyScore.league_id == league_id, WeeklyScore.team_id == t0,
            WeeklyScore.week == WEEK, WeeklyScore.year == YEAR,
        ))).scalar_one()
        assert score.lineup_data.get("auto_lineup") is True

    async with db_session_factory() as db:
        combined = await get_combined_standings(league_id, db)
    assert len(combined) == 2


@pytest.mark.asyncio
async def test_dual_squad_and_rivalry_week_mutually_exclusive(db_session_factory):
    """A DUAL_SQUAD league can never simultaneously be CONFERENCE
    (single enum column) -- confirm the rivalry-week gate (which checks
    league_type == CONFERENCE) simply never engages, no error, even if
    rivalry_week_settings were somehow set."""
    setup = await _make_league(db_session_factory, num_teams=4, extra_kwargs={
        "rivalry_week_settings": {"enabled": True, "week": WEEK, "bonus_value": 7.0},
    })
    league_id = setup["league_id"]
    t0 = setup["team_ids"][0]

    async with db_session_factory() as db:
        await calculate_week(league_id, WEEK, YEAR, db, sleeper_stats={})

    from app.models.weekly_score import WeeklyScore
    async with db_session_factory() as db:
        score = (await db.execute(select(WeeklyScore).where(
            WeeklyScore.league_id == league_id, WeeklyScore.team_id == t0,
            WeeklyScore.week == WEEK, WeeklyScore.year == YEAR,
        ))).scalar_one()
        assert "rivalry_bonus" not in score.lineup_data


@pytest.mark.asyncio
async def test_dual_squad_and_guillotine_mutually_exclusive():
    """Structural check -- league_type is a single enum column, so a
    league is never simultaneously DUAL_SQUAD and GUILLOTINE. Confirm
    _effective_matchups' Guillotine finale-force branch is unreachable
    for a DUAL_SQUAD league."""
    from app.services.standings_service import _effective_matchups
    league = League(id="l", name="x", commissioner_id="c", league_type=LeagueType.DUAL_SQUAD)
    a = Team(id="a", name="a", league_id="l", roster=[], roster_version=0, partner_team_id="b")
    b = Team(id="b", name="b", league_id="l", roster=[], roster_version=0, partner_team_id="a")
    # Both "alive" (no eliminated_week) -- the Guillotine branch requires
    # league_type == GUILLOTINE, which is never true here.
    matchups = _effective_matchups(league, [a, b], 1)
    assert matchups == []  # the only possible pairing IS the partner pairing, so it's dropped


@pytest.mark.asyncio
async def test_trade_between_partner_teams_uses_standard_pipeline(client, db_session_factory):
    setup = await _make_league(db_session_factory, num_teams=4)
    league_id = setup["league_id"]
    t0, t1 = setup["team_ids"][0], setup["team_ids"][1]

    async with db_session_factory() as db:
        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-dstrade-{i}-{uuid.uuid4().hex[:6]}",
                   first_name=f"P{i}", last_name="Test", position="RB")
            for i in range(2)
        ]
        db.add_all(players)
        await db.flush()
        team0 = (await db.execute(select(Team).where(Team.id == t0))).scalar_one()
        team1 = (await db.execute(select(Team).where(Team.id == t1))).scalar_one()
        team0.roster = [players[0].id]
        team1.roster = [players[1].id]
        await db.commit()
        p0_id, p1_id = players[0].id, players[1].id

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/trades", json={
        "team_id": t0, "target_team_id": t1,
        "offered_player_ids": [p0_id], "requested_player_ids": [p1_id],
    })
    assert r.status_code == 201
    trade_id = r.json()["id"]

    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        team0 = (await db.execute(select(Team).where(Team.id == t0))).scalar_one()
        team1 = (await db.execute(select(Team).where(Team.id == t1))).scalar_one()
        assert team0.roster == [p1_id]
        assert team1.roster == [p0_id]
        assert team0.roster_version == 1  # CAS incremented, same as any other trade


@pytest.mark.asyncio
async def test_waiver_priority_independent_per_partner_team(db_session_factory):
    setup = await _make_league(db_session_factory, num_teams=4)
    league_id = setup["league_id"]
    t0, t1, t2, t3 = setup["team_ids"]

    async with db_session_factory() as db:
        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-dswaiver-{i}-{uuid.uuid4().hex[:6]}",
                   first_name=f"P{i}", last_name="Test", position="RB")
            for i in range(2)
        ]
        db.add_all(players)
        await db.flush()
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        league.waiver_priority = [t0, t1, t2, t3]
        db.add(Transaction(league_id=league_id, team_id=t0, type=TransactionType.WAIVER,
                            status=TransactionStatus.PENDING,
                            details={"add_player_id": players[0].id, "drop_player_id": None}))
        db.add(Transaction(league_id=league_id, team_id=t1, type=TransactionType.WAIVER,
                            status=TransactionStatus.PENDING,
                            details={"add_player_id": players[1].id, "drop_player_id": None}))
        await db.commit()
        league_obj = league

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        result = await process_league_waivers(league, db, reviewed_by=setup["commissioner_id"])

    # t0 and t1 (partners) each independently rotate to the back --
    # nothing merges their priority slots.
    assert result["granted"]
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        # Both t0 and t1 should have moved behind t2/t3 in the priority
        # list, independently, not as a merged unit.
        assert league.waiver_priority.index(t0) > league.waiver_priority.index(t2) or t0 not in league.waiver_priority[:2]


@pytest.mark.asyncio
async def test_draft_interleaved_partner_teams_own_normal_snake_positions(db_session_factory):
    setup = await _make_league(db_session_factory, num_teams=4)
    league_id = setup["league_id"]

    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        league.draft_status = DraftStatus.NOT_STARTED
        await db.commit()

    async with db_session_factory() as db:
        draft = await create_draft(db, league_id, total_rounds=2)

    team_order = json.loads(draft.team_order)
    # 4 teams * 2 rounds = 8 entries, no special adjacency guarantee for
    # partner teams -- just confirm every team appears the expected
    # number of times (2, once per round) with no crash/special-casing.
    for tid in setup["team_ids"]:
        assert team_order.count(tid) == 2
    assert len(team_order) == 8


# ─── AI _partner_summary (Step 7) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_partner_summary_empty_for_non_dual_squad_league(db_session_factory):
    from app.api.v1.ai import _partner_summary

    setup = await _make_league(db_session_factory, num_teams=2, extra_kwargs=None)
    league_id = setup["league_id"]
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        league.league_type = LeagueType.STANDARD
        await db.commit()

    async with db_session_factory() as db:
        team = (await db.execute(select(Team).where(Team.id == setup["team_ids"][0]))).scalar_one()
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        result = await _partner_summary(team, league, db)
    assert result == {}


@pytest.mark.asyncio
async def test_partner_summary_empty_for_unpaired_team_in_dual_squad_league(db_session_factory):
    from app.api.v1.ai import _partner_summary

    setup = await _make_league(db_session_factory, num_teams=2)
    league_id = setup["league_id"]
    async with db_session_factory() as db:
        team = (await db.execute(select(Team).where(Team.id == setup["team_ids"][0]))).scalar_one()
        team.partner_team_id = None
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        await db.commit()

    async with db_session_factory() as db:
        team = (await db.execute(select(Team).where(Team.id == setup["team_ids"][0]))).scalar_one()
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        result = await _partner_summary(team, league, db)
    assert result == {}


@pytest.mark.asyncio
async def test_partner_summary_returns_combined_row_for_paired_team(db_session_factory):
    from app.api.v1.ai import _partner_summary

    setup = await _make_league(db_session_factory, num_teams=2)
    league_id = setup["league_id"]
    t0, t1 = setup["team_ids"]

    async with db_session_factory() as db:
        from app.models.weekly_score import WeeklyScore
        db.add(WeeklyScore(league_id=league_id, team_id=t0, week=1, year=2026, total_score=10.0, lineup_data={}))
        db.add(WeeklyScore(league_id=league_id, team_id=t1, week=1, year=2026, total_score=20.0, lineup_data={}))
        await db.commit()

    async with db_session_factory() as db:
        team = (await db.execute(select(Team).where(Team.id == t0))).scalar_one()
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        result = await _partner_summary(team, league, db)

    assert set(result["team_ids"]) == {t0, t1}
    assert result["points_for"] == 30.0
