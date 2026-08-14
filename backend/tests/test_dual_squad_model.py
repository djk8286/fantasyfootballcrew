"""
Tests for Phase 7 ("Dual-Squad/Mirror") Step 1 -- the data model itself:
Team.partner_team_id (a nullable, self-referential FK, set symmetrically)
and LeagueType.DUAL_SQUAD. Pair-creation/claiming behavior is covered
separately in test_dual_squad_pairs.py once Step 2 lands; schedule
exclusion in test_dual_squad_schedule.py (Step 3); combined standings in
test_dual_squad_standings.py (Step 4).
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.user import User


async def _make_league(db_session_factory, league_type=LeagueType.DUAL_SQUAD):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"dscommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Dual Squad Model Test League",
                         commissioner_id=commissioner.id, league_type=league_type,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_partner_team_id_column_exists_and_defaults_none(db_session_factory):
    league_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name="Solo Team", league_id=league_id, roster=[], roster_version=0)
        db.add(team)
        await db.commit()
        await db.refresh(team)
        assert team.partner_team_id is None


@pytest.mark.asyncio
async def test_symmetric_partner_link_round_trips(db_session_factory):
    league_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        a = Team(id=str(uuid.uuid4()), name="Team A", league_id=league_id, roster=[], roster_version=0)
        b = Team(id=str(uuid.uuid4()), name="Team B", league_id=league_id, roster=[], roster_version=0)
        db.add_all([a, b])
        await db.flush()
        a.partner_team_id = b.id
        b.partner_team_id = a.id
        await db.commit()
        a_id, b_id = a.id, b.id

    async with db_session_factory() as db:
        a = (await db.execute(select(Team).where(Team.id == a_id))).scalar_one()
        b = (await db.execute(select(Team).where(Team.id == b_id))).scalar_one()
        assert a.partner_team_id == b.id
        assert b.partner_team_id == a.id


@pytest.mark.asyncio
async def test_delete_team_clears_partner_pointer(db_session_factory):
    league_id = await _make_league(db_session_factory)
    async with db_session_factory() as db:
        a = Team(id=str(uuid.uuid4()), name="Team A", league_id=league_id, roster=[], roster_version=0)
        b = Team(id=str(uuid.uuid4()), name="Team B", league_id=league_id, roster=[], roster_version=0)
        db.add_all([a, b])
        await db.flush()
        a.partner_team_id = b.id
        b.partner_team_id = a.id
        await db.commit()
        a_id, b_id = a.id, b.id

    async with db_session_factory() as db:
        a = (await db.execute(select(Team).where(Team.id == a_id))).scalar_one()
        # Symmetric cleanup lives in the API layer (delete_team), not the
        # model -- mimic it directly here since this is a model-level test.
        b = (await db.execute(select(Team).where(Team.id == a.partner_team_id))).scalar_one()
        b.partner_team_id = None
        await db.delete(a)
        await db.commit()

    async with db_session_factory() as db:
        survivor = (await db.execute(select(Team).where(Team.id == b_id))).scalar_one()
        assert survivor.partner_team_id is None


@pytest.mark.asyncio
async def test_dual_squad_league_type_value():
    assert LeagueType.DUAL_SQUAD.value == "dual_squad"


@pytest.mark.asyncio
async def test_dual_squad_league_round_trips(db_session_factory):
    league_id = await _make_league(db_session_factory, league_type=LeagueType.DUAL_SQUAD)
    async with db_session_factory() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        assert league.league_type == LeagueType.DUAL_SQUAD
