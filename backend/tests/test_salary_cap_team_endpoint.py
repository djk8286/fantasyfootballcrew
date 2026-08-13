"""
Tests for GET /teams/{id}/cap (Phase 5 Step 7, "Salary-Cap + Contract
Leagues") -- team_cap_summary's shape/values, exposed as an ungated
public read.
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.player import Player
from app.models.contract import Contract, DeadMoney


async def _make_league_and_team(db_session_factory, cap_settings=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email="tcommish@test.local", username="tcommish", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="Team Cap Endpoint Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={}, salary_cap_settings=cap_settings)
        db.add(league)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Test Team", league_id=league.id, owner_id=commissioner.id, roster=[], roster_version=0)
        db.add(team)
        await db.commit()
        return league.id, team.id


async def _make_player(db_session_factory):
    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-{uuid.uuid4().hex[:8]}", first_name="A", last_name="Player", position="RB")
        db.add(player)
        await db.commit()
        return player.id


@pytest.mark.asyncio
async def test_cap_summary_matches_hand_computed_values(client, db_session_factory):
    settings = {"enabled": True, "cap_total": 100.0, "max_roster_size": 15,
                "top_salary": 50.0, "bottom_salary": 1.0, "waiver_salary_pct": 0.6,
                "dead_money_pct": 0.5, "default_contract_years": 2, "waiver_contract_years": 1}
    league_id, team_id = await _make_league_and_team(db_session_factory, cap_settings=settings)
    p1 = await _make_player(db_session_factory)
    p2 = await _make_player(db_session_factory)

    async with db_session_factory() as db:
        db.add(Contract(league_id=league_id, team_id=team_id, player_id=p1, salary=30.0, contract_years=2, signed_year=2026, source="draft", is_active=True))
        db.add(Contract(league_id=league_id, team_id=team_id, player_id=p2, salary=15.0, contract_years=1, signed_year=2026, source="waiver", is_active=True))
        db.add(DeadMoney(league_id=league_id, team_id=team_id, player_id="some-old-player", amount=5.0, reason="early release"))
        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one()
        team.roster = [p1, p2]
        await db.commit()

    r = await client.get(f"/teams/{team_id}/cap")
    assert r.status_code == 200
    body = r.json()
    assert body["cap_total"] == 100.0
    assert body["contracts_total"] == 45.0
    assert body["dead_money_total"] == 5.0
    assert body["cap_used"] == 50.0
    assert body["cap_space"] == 50.0
    assert body["roster_size"] == 2
    assert body["max_roster_size"] == 15
    assert len(body["contracts"]) == 2


@pytest.mark.asyncio
async def test_cap_space_goes_negative_when_over_cap_no_clamping(client, db_session_factory):
    settings = {"enabled": True, "cap_total": 10.0, "max_roster_size": 15,
                "top_salary": 50.0, "bottom_salary": 1.0, "waiver_salary_pct": 0.6,
                "dead_money_pct": 0.5, "default_contract_years": 2, "waiver_contract_years": 1}
    league_id, team_id = await _make_league_and_team(db_session_factory, cap_settings=settings)
    p1 = await _make_player(db_session_factory)

    async with db_session_factory() as db:
        db.add(Contract(league_id=league_id, team_id=team_id, player_id=p1, salary=30.0, contract_years=2, signed_year=2026, source="draft", is_active=True))
        await db.commit()

    r = await client.get(f"/teams/{team_id}/cap")
    assert r.status_code == 200
    body = r.json()
    assert body["cap_space"] == -20.0  # 10.0 cap_total - 30.0 used, no clamping


@pytest.mark.asyncio
async def test_cap_summary_available_even_when_cap_disabled(client, db_session_factory):
    league_id, team_id = await _make_league_and_team(db_session_factory, cap_settings=None)
    r = await client.get(f"/teams/{team_id}/cap")
    assert r.status_code == 200
    body = r.json()
    assert body["contracts"] == []
    assert body["cap_used"] == 0.0


@pytest.mark.asyncio
async def test_cap_summary_404s_for_unknown_team(client, db_session_factory):
    r = await client.get("/teams/nonexistent-team-id/cap")
    assert r.status_code == 404
