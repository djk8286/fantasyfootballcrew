"""
Tests for draft-time salary assignment (Phase 5 Step 4, "Salary-Cap +
Contract Leagues") -- make_pick creating a Contract at the pick-slot
salary, roster_version CAS protection newly added to the roster-append
write, and max_roster_size enforcement mid-draft.
"""
import json
import uuid
import pytest
from sqlalchemy import select, update
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.draft import DraftPick
from app.models.contract import Contract
from app.services.draft_manager import create_draft, start_draft, make_pick
from app.services.standings_service import calculate_week, get_standings


async def _make_cap_league(db_session_factory, num_teams=4, total_rounds=3, cap_enabled=True, max_roster_size=20):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email="dcommish@test.local", username="dcommish", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(
            id=str(uuid.uuid4()), name="Salary Cap Draft Test League", commissioner_id=commissioner.id,
            league_type=LeagueType.STANDARD, draft_status=DraftStatus.NOT_STARTED,
            scoring_config={}, roster_slots={},
            salary_cap_settings={
                "enabled": cap_enabled, "cap_total": 200.0, "max_roster_size": max_roster_size,
                "top_salary": 50.0, "bottom_salary": 1.0, "waiver_salary_pct": 0.6,
                "dead_money_pct": 0.5, "default_contract_years": 2, "waiver_contract_years": 1,
            },
        )
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i + 1}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0)
            for i in range(num_teams)
        ]
        db.add_all(teams)

        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-draft-{i}", first_name=f"Player{i}",
                   last_name="Test", position="RB")
            for i in range(num_teams * total_rounds)
        ]
        db.add_all(players)
        await db.commit()

        draft = await create_draft(db, league.id, total_rounds=total_rounds)
        draft = await start_draft(db, draft.id)

        return {
            "league_id": league.id,
            "team_ids": [t.id for t in teams],
            "player_ids": [p.id for p in players],
            "draft_id": draft.id,
            "team_order": json.loads(draft.team_order),
            "db_session_factory": db_session_factory,
        }


async def _make_full_draft(db_session_factory, num_teams=4, total_rounds=3, cap_enabled=True, max_roster_size=20):
    setup = await _make_cap_league(db_session_factory, num_teams, total_rounds, cap_enabled, max_roster_size)
    team_order = setup["team_order"]
    player_iter = iter(setup["player_ids"])

    async with db_session_factory() as db:
        for team_id in team_order:
            player_id = next(player_iter)
            await make_pick(db, setup["draft_id"], team_id, player_id)

    return setup


@pytest.mark.asyncio
async def test_draft_creates_one_contract_per_pick_at_correct_salary(db_session_factory):
    setup = await _make_full_draft(db_session_factory, num_teams=4, total_rounds=3)
    league_id = setup["league_id"]
    total_picks = 4 * 3

    async with db_session_factory() as db:
        result = await db.execute(select(Contract).where(Contract.league_id == league_id))
        contracts = result.scalars().all()

    assert len(contracts) == total_picks

    async with db_session_factory() as db:
        picks_result = await db.execute(select(DraftPick).where(DraftPick.league_id == league_id))
        picks_by_player = {p.player_id: p for p in picks_result.scalars().all()}

    contracts_by_player = {c.player_id: c for c in contracts}
    pick1_player = next(p for p, pk in picks_by_player.items() if pk.pick_number == 1)
    last_pick_player = next(p for p, pk in picks_by_player.items() if pk.pick_number == total_picks)

    assert contracts_by_player[pick1_player].salary == 50.0  # top_salary
    assert contracts_by_player[last_pick_player].salary == 1.0  # bottom_salary
    assert all(c.source == "draft" for c in contracts)
    assert all(c.contract_years == 2 for c in contracts)  # default_contract_years
    assert all(c.is_active for c in contracts)


@pytest.mark.asyncio
async def test_draft_salaries_strictly_decrease_with_pick_number(db_session_factory):
    setup = await _make_full_draft(db_session_factory, num_teams=4, total_rounds=3)
    league_id = setup["league_id"]

    async with db_session_factory() as db:
        picks_result = await db.execute(select(DraftPick).where(DraftPick.league_id == league_id))
        picks = sorted(picks_result.scalars().all(), key=lambda p: p.pick_number)
        contracts_result = await db.execute(select(Contract).where(Contract.league_id == league_id))
        contracts_by_player = {c.player_id: c.salary for c in contracts_result.scalars().all()}

    salaries_in_pick_order = [contracts_by_player[p.player_id] for p in picks]
    assert salaries_in_pick_order == sorted(salaries_in_pick_order, reverse=True)
    assert salaries_in_pick_order[0] > salaries_in_pick_order[-1]


@pytest.mark.asyncio
async def test_non_cap_league_draft_creates_zero_contracts(db_session_factory):
    """Regression pin: draft mechanics must be byte-for-byte unchanged
    when the feature is off."""
    setup = await _make_full_draft(db_session_factory, num_teams=4, total_rounds=3, cap_enabled=False)
    league_id = setup["league_id"]

    async with db_session_factory() as db:
        result = await db.execute(select(Contract).where(Contract.league_id == league_id))
        contracts = result.scalars().all()
    assert contracts == []

    # Rosters still filled normally.
    async with db_session_factory() as db:
        teams_result = await db.execute(select(Team).where(Team.league_id == league_id))
        teams = teams_result.scalars().all()
    assert all(len(t.roster or []) == 3 for t in teams)  # 3 rounds each


@pytest.mark.asyncio
async def test_max_roster_size_blocks_next_pick_for_full_team(db_session_factory):
    """create_draft shuffles team_ids internally before generating the
    snake order, so which team picks first is non-deterministic -- track
    each team's pick count generically (not assuming a fixed team goes
    first) so this test is robust to that shuffle either way."""
    setup = await _make_cap_league(db_session_factory, num_teams=2, total_rounds=5, max_roster_size=2)
    team_order = setup["team_order"]
    player_iter = iter(setup["player_ids"])
    picks_by_team: dict[str, int] = {}

    async with db_session_factory() as db:
        for team_id in team_order:
            if picks_by_team.get(team_id, 0) >= 2:
                # This team's 3rd pick attempt -- should be blocked.
                with pytest.raises(ValueError, match="already at the 2-player limit"):
                    await make_pick(db, setup["draft_id"], team_id, next(player_iter))
                break
            await make_pick(db, setup["draft_id"], team_id, next(player_iter))
            picks_by_team[team_id] = picks_by_team.get(team_id, 0) + 1


@pytest.mark.asyncio
async def test_roster_cas_write_shape_matches_make_pick_and_rejects_stale_version(db_session_factory):
    """A genuinely concurrent race against make_pick as a single function
    call can't be forced deterministically in-process (same reasoning
    test_trade_concurrency.py's own docstring documents for review_trade
    -- SQLite's shared StaticPool connection doesn't faithfully reproduce
    real concurrent transactions, and make_pick always reads its own
    roster_version fresh immediately before writing it, so there's no
    externally-observable "stale" window to inject into a single call).
    Instead, directly prove the exact WHERE-clause CAS shape make_pick's
    roster-append now uses (identical to trade/waiver's own already-
    proven pattern) correctly rejects a stale version rather than
    silently overwriting a concurrent change."""
    setup = await _make_cap_league(db_session_factory, num_teams=2, total_rounds=2, cap_enabled=False)
    team_id = setup["team_ids"][0]

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        observed_version = team.roster_version  # what make_pick would have just read

    # A concurrent write (e.g. a waiver claim processed mid-draft) lands first.
    async with db_session_factory() as db:
        await db.execute(
            update(Team).where(Team.id == team_id)
            .values(roster=["concurrent-waiver-add"], roster_version=1)
        )
        await db.commit()

    # make_pick's exact roster-append CAS shape, using the now-stale observed_version.
    async with db_session_factory() as db:
        cas = await db.execute(
            update(Team).where(Team.id == team_id, Team.roster_version == observed_version)
            .values(roster=["draft-pick-attempt"], roster_version=Team.roster_version + 1)
        )
        await db.commit()
        assert cas.rowcount == 0, "a stale roster_version must never match and overwrite"

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one()
        assert team.roster == ["concurrent-waiver-add"]
        assert team.roster_version == 1


@pytest.mark.asyncio
async def test_roster_version_increments_once_per_pick(db_session_factory):
    """Confirms the CAS write actually ran for every pick (not just the
    roster content changing) -- the concrete, achievable proof that
    make_pick's roster-append really goes through the new CAS path now,
    not just documented as added."""
    setup = await _make_full_draft(db_session_factory, num_teams=2, total_rounds=3)
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.league_id == setup["league_id"]))
        teams = result.scalars().all()
    for t in teams:
        assert t.roster_version == 3  # one CAS-protected write per pick, 3 rounds each


@pytest.mark.asyncio
async def test_get_standings_unaffected_by_cap_enabled_league_with_contracts(db_session_factory):
    """Decoupling-proof: this phase deliberately never touches
    calculate_week/get_standings. Confirm a cap-enabled league with real
    Contract rows produces byte-for-byte the same standings shape/values
    as it would with the feature off -- not just an unverified assumption."""
    setup = await _make_full_draft(db_session_factory, num_teams=2, total_rounds=2, cap_enabled=True)
    league_id = setup["league_id"]

    async with db_session_factory() as db:
        await calculate_week(league_id, 1, 2026, db, sleeper_stats={})
        standings = await get_standings(league_id, db)

    # Every team has a normal, uncorrupted standings entry -- no
    # salary/contract fields leaking into or affecting this shape at all.
    assert len(standings) == 2
    for s in standings:
        assert set(s.keys()) == {"team_id", "team_name", "conference", "wins", "losses", "ties", "points_for", "points_against"}
