"""Commissioner hub data: members by username, and co-commissioner
changes by username instead of raw user id."""
import pytest

from app.models.league import League
from tests.test_roster_activity import _league, _season


@pytest.mark.asyncio
async def test_members_lists_usernames_for_managers_only(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    r = await client.get(f"/leagues/{s['league']}/members", headers=s["alice"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["viewer_is_owner"] is True
    assert body["commissioner"]["username"] == "alice"
    assert body["co_commissioners"] == []
    by_team = {t["name"]: t for t in body["teams"]}
    assert by_team["Aces"]["owner"]["username"] == "alice"
    assert by_team["Bolts"]["owner"]["username"] == "bob"
    assert [m["username"] for m in body["members"]] == ["alice", "bob"]
    assert body["members"][1]["teams"] == ["Bolts"]

    assert (await client.get(f"/leagues/{s['league']}/members", headers=s["bob"])).status_code == 403
    assert (await client.get(f"/leagues/{s['league']}/members")).status_code == 401


@pytest.mark.asyncio
async def test_add_and_remove_co_commissioner_by_username(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    url = f"/leagues/{s['league']}/commissioner"
    r = await client.post(url, json={"action": "add_co_commish", "identifier": "@Bob"}, headers=s["alice"])
    assert r.status_code == 200, r.text
    body = (await client.get(f"/leagues/{s['league']}/members", headers=s["alice"])).json()
    assert [c["username"] for c in body["co_commissioners"]] == ["bob"]

    # A co-commissioner can see the hub but not change who runs it.
    as_bob = (await client.get(f"/leagues/{s['league']}/members", headers=s["bob"])).json()
    assert as_bob["viewer_is_owner"] is False
    assert (await client.post(url, json={"action": "remove_co_commish", "identifier": "alice"}, headers=s["bob"])).status_code == 403

    bob_id = body["co_commissioners"][0]["user_id"]
    r = await client.post(url, json={"action": "remove_co_commish", "user_id": bob_id}, headers=s["alice"])
    assert r.status_code == 200
    async with db_session_factory() as db:
        assert (await db.get(League, s["league"])).co_commissioner_ids == []


@pytest.mark.asyncio
async def test_unknown_or_missing_identifier(client, db_session_factory):
    s = await _league(db_session_factory, weeks=_season())
    url = f"/leagues/{s['league']}/commissioner"
    r = await client.post(url, json={"action": "add_co_commish", "identifier": "nobody"}, headers=s["alice"])
    assert r.status_code == 404 and "username" in r.json()["detail"]
    assert (await client.post(url, json={"action": "add_co_commish"}, headers=s["alice"])).status_code == 400
