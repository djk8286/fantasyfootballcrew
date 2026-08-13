"""
Tests for Coaches & Coordinators cap enforcement and bonus_type validation
(Phase 2 Step 1, "Front-Office finish-out"). Before this, a team could
create unlimited coaches at any position, and bonus_type accepted any
free-form string with no scoring effect beyond "flat_weekly".
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League
from app.models.team import Team
from app.models.coach import Coach, CoachPosition
from app.services.auth_service import create_access_token


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Coach Cap Test League", commissioner_id=commissioner_id,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


async def _make_team(db_session_factory, league_id, owner_id=None, co_owner_id=None):
    async with db_session_factory() as db:
        team = Team(id=str(uuid.uuid4()), name="Test Team", league_id=league_id,
                    owner_id=owner_id, co_owner_id=co_owner_id, is_cpu=False, roster=[])
        db.add(team)
        await db.commit()
        return team.id


async def _add_coach(db_session_factory, team_id, position, is_active=True):
    async with db_session_factory() as db:
        coach = Coach(id=str(uuid.uuid4()), name=f"Coach {position}", position=position,
                      team_id=team_id, is_active=is_active)
        db.add(coach)
        await db.commit()
        return coach.id


@pytest.mark.asyncio
async def test_owner_can_hire_one_coach_per_position(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {token}"
    for position in ["HC", "OC", "DC", "STC"]:
        r = await client.post(f"/teams/{team_id}/coaches", json={"name": f"Coach {position}", "position": position})
        assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_second_coach_at_same_position_rejected(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r1 = await client.post(f"/teams/{team_id}/coaches", json={"name": "First HC", "position": "HC"})
    assert r1.status_code == 201
    r2 = await client.post(f"/teams/{team_id}/coaches", json={"name": "Second HC", "position": "HC"})
    assert r2.status_code == 400

    # The first HC is unaffected by the rejected second attempt.
    r3 = await client.get(f"/teams/{team_id}/coaches")
    assert len(r3.json()) == 1


@pytest.mark.asyncio
async def test_co_owner_hits_the_same_cap(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    co_owner, co_owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id, co_owner_id=co_owner.id)
    await _add_coach(db_session_factory, team_id, CoachPosition.HC)

    client.headers["Authorization"] = f"Bearer {co_owner_token}"
    r = await client.post(f"/teams/{team_id}/coaches", json={"name": "Second HC", "position": "HC"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stranger_cannot_hire_a_coach(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    stranger, stranger_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {stranger_token}"
    r = await client.post(f"/teams/{team_id}/coaches", json={"name": "Coach X", "position": "HC"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_cannot_hire_a_coach(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers.pop("Authorization", None)
    r = await client.post(f"/teams/{team_id}/coaches", json={"name": "Coach X", "position": "HC"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_coaches_requires_no_auth(client, db_session_factory):
    """Deliberately still true after Phase 2 -- matches house style for
    team-level reads (get_team/get_league_teams), not a gap to close."""
    owner, _owner_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)
    await _add_coach(db_session_factory, team_id, CoachPosition.HC)

    client.headers.pop("Authorization", None)
    r = await client.get(f"/teams/{team_id}/coaches")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_delete_then_recreate_at_same_position_allowed(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)
    coach_id = await _add_coach(db_session_factory, team_id, CoachPosition.HC)

    client.headers["Authorization"] = f"Bearer {token}"
    r1 = await client.delete(f"/coaches/{coach_id}")
    assert r1.status_code == 204
    r2 = await client.post(f"/teams/{team_id}/coaches", json={"name": "New HC", "position": "HC"})
    assert r2.status_code == 201


@pytest.mark.asyncio
async def test_invalid_bonus_type_rejected(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post(
        f"/teams/{team_id}/coaches",
        json={"name": "Coach X", "position": "HC", "bonus_type": "made_up_bonus"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_win_bonus_is_a_valid_bonus_type(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.post(
        f"/teams/{team_id}/coaches",
        json={"name": "Coach X", "position": "HC", "bonus_type": "win_bonus", "bonus_value": 5},
    )
    assert r.status_code == 201
    assert r.json()["bonus_type"] == "win_bonus"


@pytest.mark.asyncio
async def test_patch_position_change_onto_filled_position_rejected(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)
    await _add_coach(db_session_factory, team_id, CoachPosition.HC)
    oc_id = await _add_coach(db_session_factory, team_id, CoachPosition.OC)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.patch(f"/coaches/{oc_id}", json={"position": "HC"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_patch_reactivation_onto_filled_position_rejected(client, db_session_factory):
    owner, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)
    team_id = await _make_team(db_session_factory, league_id, owner_id=owner.id)
    benched_hc_id = await _add_coach(db_session_factory, team_id, CoachPosition.HC, is_active=False)
    await _add_coach(db_session_factory, team_id, CoachPosition.HC)  # fills the slot the benched one vacated

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.patch(f"/coaches/{benched_hc_id}", json={"is_active": True})
    assert r.status_code == 400
