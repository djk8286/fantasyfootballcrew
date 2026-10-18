"""
QA round 1 (2026-10-17): logged-out visitors were shown owner/member
controls on prod (Set Lineup, Add Coach, Save Lineup, waiver Submit Claim,
Propose Trade, Create League). That was a frontend null === null compare;
these tests pin down that the *server* rejects every one of those
mutations for (a) no token and (b) a logged-in user who isn't in the
league -- including against an ownerless CPU team, where owner_id and
co_owner_id are both NULL.
"""
import uuid
import pytest
from app.models.user import User
from app.models.league import League, LeagueVisibility
from app.models.team import Team
from app.services.auth_service import create_access_token


async def _user(f):
    async with f() as db:
        u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                 username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(u)
        await db.commit()
        return u, create_access_token({"sub": u.id, "email": u.email, "token_version": 0})


async def _setup(f, visibility=LeagueVisibility.INVITE_ONLY):
    owner, owner_token = await _user(f)
    async with f() as db:
        league = League(id=str(uuid.uuid4()), name="Authz League", commissioner_id=owner.id,
                        scoring_config={}, roster_slots={"QB": 1}, visibility=visibility)
        db.add(league)
        owned = Team(id=str(uuid.uuid4()), name="Owned", league_id=league.id,
                     owner_id=owner.id, is_cpu=False, roster=[])
        cpu = Team(id=str(uuid.uuid4()), name="CPU", league_id=league.id,
                   owner_id=None, co_owner_id=None, is_cpu=True, roster=[])
        db.add_all([owned, cpu])
        await db.commit()
        return {"league_id": league.id, "owned": owned.id, "cpu": cpu.id}


def _mutations(s):
    lid = s["league_id"]
    out = []
    for team in (s["owned"], s["cpu"]):
        out += [
            ("put", f"/teams/{team}/lineup?week=1&year=2026", {"starters": []}),
            ("post", f"/teams/{team}/lineup/optimize?week=1&year=2026", None),
            ("post", f"/teams/{team}/coaches", {"name": "X", "position": "HC"}),
            ("post", f"/leagues/{lid}/waivers/claims", {"team_id": team, "add_player_id": "p1"}),
            ("post", f"/leagues/{lid}/trades", {"team_id": team,
                                                "target_team_id": s["owned"] if team == s["cpu"] else s["cpu"],
                                                "offered_player_ids": [], "requested_player_ids": []}),
            ("post", f"/teams/{team}/claim", None),
            ("post", f"/teams/{team}/claim-co-owner", None),
        ]
    return out


async def _call(client, method, url, body):
    fn = getattr(client, method)
    return await (fn(url, json=body) if body is not None else fn(url))


@pytest.mark.asyncio
async def test_anonymous_cannot_mutate(client, db_session_factory):
    s = await _setup(db_session_factory)
    client.headers.pop("Authorization", None)
    for method, url, body in _mutations(s) + [("post", "/leagues", {"name": "Anon League"})]:
        r = await _call(client, method, url, body)
        assert r.status_code == 401, (method, url, r.status_code, r.text)


@pytest.mark.asyncio
async def test_non_member_cannot_mutate_invite_only_league(client, db_session_factory):
    s = await _setup(db_session_factory)
    _, stranger_token = await _user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {stranger_token}"
    for method, url, body in _mutations(s):
        r = await _call(client, method, url, body)
        assert r.status_code in (400, 403), (method, url, r.status_code, r.text)
        assert r.status_code != 200 and r.status_code != 201

    # And nothing changed: neither team picked up an owner or a coach.
    r = await client.get(f"/teams/league/{s['league_id']}")
    by_id = {t["id"]: t for t in r.json()}
    assert by_id[s["cpu"]]["owner_id"] is None and by_id[s["cpu"]]["co_owner_id"] is None
    assert by_id[s["owned"]]["co_owner_id"] is None
    for team in (s["owned"], s["cpu"]):
        assert (await client.get(f"/teams/{team}/coaches")).json() == []
