"""QA 2026-10-20 retest: one visibility rule for rosters and lineups.

Rosters (who's on a team) are public for OPEN and INVITE_ONLY leagues and
members-only for PRIVATE ones. Lineup data -- slot assignments, starters,
lineup issues, projected totals built from lineups, per-player box scores
-- also needs a login (deps.can_view_rosters / can_view_lineups). Every
endpoint that returns roster or lineup data is hit logged out here."""
import uuid

import pytest

from app.models.league import DraftStatus, League, LeagueType, LeagueVisibility
from app.models.player import Player
from app.models.team import Team
from app.models.user import User
from app.models.weekly_score import WeeklyScore
from app.services.auth_service import create_access_token

YEAR, WEEK = 2026, 7
WK = {"week": WEEK, "year": YEAR}


async def _user(f):
    async with f() as db:
        u = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local",
                 username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(u)
        await db.commit()
        return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'email': u.email, 'token_version': 0})}"}, u.id


async def _league(f, visibility):
    owner_auth, owner_id = await _user(f)
    other_auth, other_id = await _user(f)
    async with f() as db:
        league = League(id=str(uuid.uuid4()), name="Vis League", commissioner_id=owner_id,
                        league_type=LeagueType.STANDARD, draft_status=DraftStatus.COMPLETED,
                        scoring_config={}, roster_slots={"QB": 1, "RB": 1}, visibility=visibility)
        players = [Player(id=str(uuid.uuid4()), sleeper_id=f"s{uuid.uuid4().hex[:8]}", first_name=n,
                          last_name="Vis", position=pos, team="KC")
                   for n, pos in [("Lamar", "QB"), ("Bijan", "RB"), ("Cam", "QB"), ("Free", "RB")]]
        mine = Team(id=str(uuid.uuid4()), name="Mine", league_id=league.id, owner_id=owner_id,
                    roster=[players[0].id, players[1].id], roster_version=0)
        theirs = Team(id=str(uuid.uuid4()), name="Theirs", league_id=league.id, owner_id=other_id,
                      roster=[players[2].id], roster_version=0)
        ws = WeeklyScore(league_id=league.id, team_id=mine.id, week=WEEK, year=YEAR, total_score=12.5,
                         lineup_data={"total": 12.5, "breakdown": {players[0].id: {"score": 12.5, "position": "QB"}}})
        db.add_all([league, *players, mine, theirs, ws])
        await db.commit()
    return {"league": league.id, "team": mine.id, "owner": owner_auth, "member": other_auth,
            "players": [p.id for p in players]}


def _anon(client):
    client.headers.pop("Authorization", None)
    client.cookies.clear()


PUBLIC = [LeagueVisibility.OPEN, LeagueVisibility.INVITE_ONLY]


# ─── Logged out, public league: rosters yes, lineups no ──────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", PUBLIC)
async def test_guest_public_league_gets_rosters_but_no_lineup_data(client, db_session_factory, monkeypatch, visibility):
    import app.services.league_home_service as home
    async def fake_projections(*a, **k):
        return {"any": {}}
    monkeypatch.setattr(home, "week_projections", fake_projections)
    s = await _league(db_session_factory, visibility)
    _anon(client)

    assert (await client.get(f"/teams/{s['team']}/lineup", params=WK)).status_code == 401

    r = await client.get(f"/teams/{s['team']}/roster", params=WK)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lineup_visible"] is False
    assert body["slots"] is None and body["issues"] is None and body["has_lineup_set"] is None
    assert len(body["roster"]) == 2
    assert all(p["slot"] is None and p["is_starter"] is None for p in body["roster"])

    home_r = await client.get(f"/leagues/{s['league']}/home", params=WK)
    assert home_r.status_code == 200, home_r.text
    sides = [side for m in home_r.json()["scoreboard"] for side in (m["team_a"], m["team_b"])]
    assert sides and all(side["projected"] is None for side in sides)

    weekly = await client.get(f"/leagues/{s['league']}/standings/weekly", params=WK)
    assert weekly.status_code == 200
    assert all(ts["lineup_data"] is None for ts in weekly.json()["team_scores"])
    assert weekly.json()["team_scores"][0]["total_score"] == 12.5

    assert (await client.get(f"/teams/{s['team']}")).json()["roster"] == s["players"][:2]
    assert {len(t["roster"]) for t in (await client.get(f"/teams/league/{s['league']}")).json()} == {1, 2}
    assert (await client.get(f"/teams/{s['team']}/news")).status_code == 200
    assert (await client.get(f"/teams/{s['team']}/cap")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", PUBLIC)
async def test_logged_in_stranger_sees_public_league_lineups(client, db_session_factory, monkeypatch, visibility):
    import app.services.league_home_service as home
    async def fake_projections(*a, **k):
        return {"any": {}}
    monkeypatch.setattr(home, "week_projections", fake_projections)
    s = await _league(db_session_factory, visibility)
    stranger, _ = await _user(db_session_factory)
    _anon(client)

    body = (await client.get(f"/teams/{s['team']}/roster", params=WK, headers=stranger)).json()
    assert body["lineup_visible"] is True and body["slots"]
    assert {p["slot"] for p in body["roster"]} <= {"QB", "RB", "BN"}
    sides = [side for m in (await client.get(f"/leagues/{s['league']}/home", params=WK, headers=stranger)).json()["scoreboard"]
             for side in (m["team_a"], m["team_b"])]
    assert all(side["projected"] is not None for side in sides)
    weekly = (await client.get(f"/leagues/{s['league']}/standings/weekly", params=WK, headers=stranger)).json()
    assert weekly["team_scores"][0]["lineup_data"]["breakdown"]


# ─── PRIVATE league: members only ─────────────────────────────────────────

GATED = [
    "/teams/{team}/lineup?week=7&year=2026",
    "/teams/{team}/roster?week=7&year=2026",
    "/leagues/{league}/home?week=7&year=2026",
    "/leagues/{league}/standings/weekly?week=7&year=2026",
    "/teams/{team}/news",
    "/teams/{team}/cap",
]


@pytest.mark.asyncio
async def test_private_league_guest_401_stranger_403_member_200(client, db_session_factory):
    s = await _league(db_session_factory, LeagueVisibility.PRIVATE)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    for path in GATED:
        url = path.format(**s)
        assert (await client.get(url)).status_code == 401, url
        assert (await client.get(url, headers=stranger)).status_code == 403, url
        assert (await client.get(url, headers=s["member"])).status_code == 200, url
        assert (await client.get(url, headers=s["owner"])).status_code == 200, url


@pytest.mark.asyncio
async def test_private_league_team_reads_hide_rosters_from_non_members(client, db_session_factory):
    """Team names/records stay readable (invitees pick a team to claim from
    them); the roster does not."""
    s = await _league(db_session_factory, LeagueVisibility.PRIVATE)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    for headers in ({}, stranger):
        team = await client.get(f"/teams/{s['team']}", headers=headers)
        assert team.status_code == 200 and team.json()["name"] == "Mine" and team.json()["roster"] is None
        teams = (await client.get(f"/teams/league/{s['league']}", headers=headers)).json()
        assert [t["roster"] for t in teams] == [None, None]
    assert (await client.get(f"/teams/{s['team']}", headers=s["member"])).json()["roster"] == s["players"][:2]


@pytest.mark.asyncio
async def test_api_responses_are_not_cacheable(client, db_session_factory):
    s = await _league(db_session_factory, LeagueVisibility.OPEN)
    _anon(client)
    r = await client.get(f"/teams/{s['team']}", headers=s["owner"])
    assert r.headers["cache-control"] == "private, no-store"


# ─── Waiver search: free agents only (QA 2026-10-20, Lamar Jackson) ──────

@pytest.mark.asyncio
async def test_player_search_available_in_league_skips_every_rostered_player(client, db_session_factory):
    s = await _league(db_session_factory, LeagueVisibility.OPEN)
    _anon(client)
    everyone = (await client.get("/players", params={"search": "Vis", "limit": 50})).json()
    assert {p["id"] for p in everyone} == set(s["players"])
    free = (await client.get("/players", params={"search": "Vis", "limit": 50,
                                                 "available_in_league": s["league"]})).json()
    # Lamar/Bijan on my roster, Cam on the other team: only "Free" is left.
    assert [p["id"] for p in free] == [s["players"][3]]
    fa = (await client.get(f"/leagues/{s['league']}/waivers/free-agents")).json()
    listed = {p["id"] for group in fa.values() for p in group}
    assert s["players"][3] in listed and not listed & set(s["players"][:3])


@pytest.mark.asyncio
async def test_private_league_accepted_invitee_can_look_before_claiming(client, db_session_factory):
    from datetime import datetime, timedelta, timezone
    from app.models.league_invite import InviteStatus, LeagueInvite
    s = await _league(db_session_factory, LeagueVisibility.PRIVATE)
    invitee, invitee_id = await _user(db_session_factory)
    async with db_session_factory() as db:
        db.add(LeagueInvite(league_id=s["league"], invited_email="x@t.local", token_hash=uuid.uuid4().hex,
                            status=InviteStatus.ACCEPTED, accepted_by_user_id=invitee_id,
                            expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
        await db.commit()
    _anon(client)
    assert (await client.get(f"/leagues/{s['league']}/home", params=WK, headers=invitee)).status_code == 200
    assert (await client.get(f"/teams/{s['team']}", headers=invitee)).json()["roster"] == s["players"][:2]
