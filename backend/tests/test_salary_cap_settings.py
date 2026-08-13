"""
Tests for the Salary-Cap settings API (Phase 5 Step 3, "Salary-Cap +
Contract Leagues") -- GET/PUT /leagues/{id}/salary-cap-settings, and
(Step 6) GET /leagues/{id}/salary-cap/preview-signing. Cap enforcement
itself (draft/waiver/trade actually respecting these settings) is
covered separately once Steps 4/5/8 land.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.player import Player
from app.services.auth_service import create_access_token
from app.services.salary_cap_service import DEFAULT_SALARY_CAP_SETTINGS


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league(db_session_factory, commissioner_id, league_type=LeagueType.STANDARD):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Salary Cap Settings Test League", commissioner_id=commissioner_id,
                         league_type=league_type, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        return league.id


@pytest.mark.asyncio
async def test_get_salary_cap_settings_defaults(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    r = await client.get(f"/leagues/{league_id}/salary-cap-settings")
    assert r.status_code == 200
    assert r.json() == DEFAULT_SALARY_CAP_SETTINGS


@pytest.mark.asyncio
async def test_commissioner_can_set_salary_cap_settings(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    payload = {
        "enabled": True, "cap_total": 300.0, "max_roster_size": 25,
        "top_salary": 60.0, "bottom_salary": 2.0, "waiver_salary_pct": 0.5,
        "dead_money_pct": 0.4, "default_contract_years": 3, "waiver_contract_years": 1,
    }
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": payload})
    assert r.status_code == 200
    assert r.json()["salary_cap_settings"] == payload

    r = await client.get(f"/leagues/{league_id}/salary-cap-settings")
    assert r.json() == payload


@pytest.mark.asyncio
async def test_put_merges_onto_defaults(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"cap_total": 150.0}})
    assert r.status_code == 200
    body = r.json()["salary_cap_settings"]
    assert body["cap_total"] == 150.0
    assert body["max_roster_size"] == DEFAULT_SALARY_CAP_SETTINGS["max_roster_size"]
    assert body["enabled"] is False


@pytest.mark.asyncio
async def test_non_commissioner_cannot_update(client, db_session_factory):
    owner, _owner_token = await _make_user(db_session_factory)
    outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, owner.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"enabled": True}})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_cannot_update(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"enabled": True}})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_top_salary_below_bottom_salary_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings",
                          json={"salary_cap_settings": {"top_salary": 5.0, "bottom_salary": 10.0}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_negative_cap_total_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"cap_total": -50.0}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_negative_max_roster_size_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"max_roster_size": 0}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dead_money_pct_out_of_range_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"dead_money_pct": 1.5}})
    assert r.status_code == 422
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"dead_money_pct": -0.1}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_contract_years_out_of_range_rejected(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"default_contract_years": 5}})
    assert r.status_code == 422
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"waiver_contract_years": 0}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_enabling_works_for_any_league_type(client, db_session_factory):
    """Unlike Rivalry Week (Conference-only), salary cap is a bolt-on
    that works on any league_type -- confirm no rejection for STANDARD."""
    user, token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id, league_type=LeagueType.STANDARD)

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.put(f"/leagues/{league_id}/salary-cap-settings", json={"salary_cap_settings": {"enabled": True}})
    assert r.status_code == 200


# ─── Step 6: preview-signing ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preview_signing_matches_compute_waiver_salary(client, db_session_factory):
    from app.services.salary_cap_service import compute_waiver_salary, get_salary_cap_settings

    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id="sleeper-preview-1",
                         first_name="Preview", last_name="Player", position="RB")
        db.add(player)
        league_result = await db.get(League, league_id)
        await db.commit()
        expected = compute_waiver_salary(player, get_salary_cap_settings(league_result))
        player_id = player.id

    r = await client.get(f"/leagues/{league_id}/salary-cap/preview-signing", params={"player_id": player_id})
    assert r.status_code == 200
    assert r.json() == {"player_id": player_id, "estimated_salary": expected}


@pytest.mark.asyncio
async def test_preview_signing_works_when_cap_disabled(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id="sleeper-preview-2",
                         first_name="Still", last_name="Works", position="WR")
        db.add(player)
        await db.commit()
        player_id = player.id

    r = await client.get(f"/leagues/{league_id}/salary-cap/preview-signing", params={"player_id": player_id})
    assert r.status_code == 200
    assert r.json()["estimated_salary"] > 0


@pytest.mark.asyncio
async def test_preview_signing_404s_for_unknown_player(client, db_session_factory):
    user, _token = await _make_user(db_session_factory)
    league_id = await _make_league(db_session_factory, user.id)

    r = await client.get(f"/leagues/{league_id}/salary-cap/preview-signing", params={"player_id": "nonexistent"})
    assert r.status_code == 404
