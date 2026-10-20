"""GET /teams/{id}/lineup needs a login. OPEN and INVITE_ONLY leagues are
readable by any logged-in user; PRIVATE leagues only by members (team
owner/co-owner, commissioner/co-commissioner)."""
import uuid

import pytest

from app.models.league import DraftStatus, League, LeagueType, LeagueVisibility
from app.models.team import Team
from app.models.user import User
from app.services.auth_service import create_access_token

PARAMS = {"week": 7, "year": 2026}


async def _user(f):
    async with f() as db:
        u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local",
                 username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(u)
        await db.commit()
        return u.id, create_access_token({"sub": u.id, "email": u.email, "token_version": 0})


async def _league(f, visibility):
    commish, commish_tok = await _user(f)
    co_commish, co_commish_tok = await _user(f)
    owner, owner_tok = await _user(f)
    co_owner, co_owner_tok = await _user(f)
    other_owner, other_owner_tok = await _user(f)
    async with f() as db:
        league = League(id=str(uuid.uuid4()), name="Read League", commissioner_id=commish,
                        co_commissioner_ids=[co_commish], league_type=LeagueType.STANDARD,
                        draft_status=DraftStatus.COMPLETED, scoring_config={}, roster_slots={"QB": 1},
                        visibility=visibility)
        team = Team(id=str(uuid.uuid4()), name="Target", league_id=league.id, owner_id=owner,
                    co_owner_id=co_owner, roster=[], roster_version=0)
        other = Team(id=str(uuid.uuid4()), name="Other", league_id=league.id, owner_id=other_owner,
                     roster=[], roster_version=0)
        db.add_all([league, team, other])
        await db.commit()
    return team.id, {"commish": commish_tok, "co_commish": co_commish_tok, "owner": owner_tok,
                     "co_owner": co_owner_tok, "other_owner": other_owner_tok}


async def _get(client, team_id, token=None):
    client.headers.pop("Authorization", None)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.get(f"/teams/{team_id}/lineup", params=PARAMS, headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", list(LeagueVisibility))
async def test_anonymous_gets_401(client, db_session_factory, visibility):
    team_id, _ = await _league(db_session_factory, visibility)
    r = await _get(client, team_id)
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", [LeagueVisibility.OPEN, LeagueVisibility.INVITE_ONLY])
async def test_public_league_readable_by_any_logged_in_user(client, db_session_factory, visibility):
    team_id, _ = await _league(db_session_factory, visibility)
    _, stranger = await _user(db_session_factory)
    r = await _get(client, team_id, stranger)
    assert r.status_code == 200, r.text
    assert r.json()["team_id"] == team_id


@pytest.mark.asyncio
async def test_private_league_hidden_from_non_members(client, db_session_factory):
    team_id, _ = await _league(db_session_factory, LeagueVisibility.PRIVATE)
    _, stranger = await _user(db_session_factory)
    r = await _get(client, team_id, stranger)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["commish", "co_commish", "owner", "co_owner", "other_owner"])
async def test_private_league_readable_by_members(client, db_session_factory, who):
    team_id, tokens = await _league(db_session_factory, LeagueVisibility.PRIVATE)
    r = await _get(client, team_id, tokens[who])
    assert r.status_code == 200, (who, r.text)


@pytest.mark.asyncio
async def test_access_cookie_is_accepted(client, db_session_factory):
    """The site sends the HttpOnly ffc_access cookie, not a Bearer header."""
    team_id, tokens = await _league(db_session_factory, LeagueVisibility.PRIVATE)
    client.headers.pop("Authorization", None)
    client.cookies.set("ffc_access", tokens["owner"])
    try:
        r = await client.get(f"/teams/{team_id}/lineup", params=PARAMS)
    finally:
        client.cookies.clear()
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_unknown_team_still_404_for_logged_in_user(client, db_session_factory):
    _, stranger = await _user(db_session_factory)
    r = await _get(client, str(uuid.uuid4()), stranger)
    assert r.status_code == 404
