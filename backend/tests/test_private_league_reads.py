"""QA 2026-10-21: a PRIVATE league is members-only on EVERY read, not just
rosters and lineups (standings were public). deps.require_league_view /
require_team_league_view / require_draft_league_view apply #35's rule:
guest 401, logged-in non-member 403, members, commissioner and accepted
invitees 200. OPEN and INVITE_ONLY leagues are unchanged.

test_every_league_scoped_get_route_is_classified walks the app's routes so
a new GET under /leagues/{id}, /teams/{id} or /drafts/{id} can't ship
without a decision here."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from app.models.draft import Draft
from app.models.league import LeagueVisibility
from app.models.league_invite import InviteStatus, LeagueInvite
from tests.test_lineup_visibility import _anon, _league, _user

# Every GET a non-member must not read in a PRIVATE league. {league},
# {team}, {draft}, {player} are filled per test.
GATED = [
    "/leagues/{league}",
    "/leagues/{league}/scoring",
    "/leagues/{league}/roster-slots",
    "/leagues/{league}/playoff-settings",
    "/leagues/{league}/rivalry-week-settings",
    "/leagues/{league}/salary-cap-settings",
    "/leagues/{league}/salary-cap/preview-signing?player_id={player}",
    "/leagues/{league}/best-ball-settings",
    "/leagues/{league}/ai-settings",
    "/leagues/{league}/management-window",
    "/leagues/{league}/team-recap",
    "/leagues/{league}/home?week=7&year=2026",
    "/leagues/{league}/activity",
    "/leagues/{league}/playoffs",
    "/leagues/{league}/standings",
    "/leagues/{league}/standings/weekly?week=7&year=2026",
    "/leagues/{league}/standings/schedule?year=2026",
    "/leagues/{league}/trades",
    "/leagues/{league}/waivers/free-agents",
    "/leagues/{league}/waivers/claims",
    "/leagues/{league}/waivers/priority",
    "/leagues/{league}/commissioner/adjustments",
    "/leagues/{league}/commissioner/trades",
    "/leagues/{league}/commissioner/draft-order",
    "/scoring/league/{league}",
    "/drafts/find?league_id={league}",
    "/drafts/{draft}/state",
    "/teams/league/{league}",
    "/teams/{team}",
    "/teams/{team}/roster?week=7&year=2026",
    "/teams/{team}/lineup?week=7&year=2026",
    "/teams/{team}/cap",
    "/teams/{team}/news",
    "/teams/{team}/coaches",
    "/players?search=Vis&available_in_league={league}",
]
# Need a login in every league (lineup data), so guests 401 even when OPEN.
LOGIN_EVERYWHERE = {"/teams/{team}/lineup?week=7&year=2026"}
# /leagues/{id}/standings/combined only exists for dual-squad leagues (404
# here); it is gated by the same dependency, checked in its own test.

# Already need more than membership (commissioner, the user's own data,
# or admin) -- unchanged, listed so the walk below accounts for them.
STRICTER = {
    "/leagues/{league_id}/members", "/leagues/{league_id}/invites", "/leagues/{league_id}/join-requests",
    "/leagues/{league_id}/commissioner/digest", "/leagues/{league_id}/commissioner/health",
    "/leagues/{league_id}/commissioner/insights", "/leagues/{league_id}/commissioner/schedule-insights",
    "/leagues/{league_id}/commissioner/chat", "/drafts/{draft_id}/autopick", "/drafts/{draft_id}/queue",
    "/admin/leagues/{league_id}",
}


async def _setup(f, visibility):
    s = await _league(f, visibility)
    async with f() as db:
        d = Draft(id=str(uuid.uuid4()), league_id=s["league"], current_round=1, current_pick=1,
                  team_order=json.dumps([s["team"]]))
        db.add(d)
        await db.commit()
    s["draft"] = d.id
    s["player"] = s["players"][3]
    return s


def _url(path, s):
    return path.format(league=s["league"], team=s["team"], draft=s["draft"], player=s["player"])


def test_every_league_scoped_get_route_is_classified():
    gated = {p.split("?")[0].replace("{league}", "{league_id}").replace("{team}", "{team_id}").replace("{draft}", "{draft_id}")
             for p in GATED}
    gated.add("/leagues/{league_id}/standings/combined")
    seen = set()
    # openapi() lists every included route (app.routes nests them lazily).
    for path, ops in app.openapi()["paths"].items():
        if "get" not in ops or not any(k in path for k in ("{league_id}", "{team_id}", "{draft_id}")):
            continue
        p = path.removeprefix("/api/v1")
        seen.add(p)
        assert p in gated or p in STRICTER, f"unclassified league-scoped GET {p}"
    # league_id as a query param (not in the path), gated all the same.
    assert gated - {"/players", "/drafts/find"} <= seen, gated - seen


@pytest.mark.asyncio
async def test_private_league_every_read_guest_401_stranger_403_members_200(client, db_session_factory):
    s = await _setup(db_session_factory, LeagueVisibility.PRIVATE)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    for path in GATED:
        url = _url(path, s)
        assert (await client.get(url)).status_code == 401, url
        assert (await client.get(url, headers=stranger)).status_code == 403, url
        for who in ("member", "owner"):
            r = await client.get(url, headers=s[who])
            assert r.status_code == 200, (who, url, r.status_code, r.text[:200])


@pytest.mark.asyncio
async def test_private_league_detail_gate_carries_only_the_name(client, db_session_factory):
    s = await _setup(db_session_factory, LeagueVisibility.PRIVATE)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    r = await client.get(f"/leagues/{s['league']}")
    assert r.status_code == 401
    assert r.json()["detail"]["league"] == {"id": s["league"], "name": "Vis League", "visibility": "private"}
    r = await client.get(f"/leagues/{s['league']}", headers=stranger)
    assert r.status_code == 403
    assert r.json()["detail"]["league"]["name"] == "Vis League"
    assert r.json()["detail"]["league"]["viewer_join_status"] == "blocked"
    assert "scoring_config" not in json.dumps(r.json())


@pytest.mark.asyncio
async def test_private_league_combined_standings_is_gated(client, db_session_factory):
    s = await _setup(db_session_factory, LeagueVisibility.PRIVATE)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    url = f"/leagues/{s['league']}/standings/combined"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=stranger)).status_code == 403
    assert (await client.get(url, headers=s["member"])).status_code == 400  # members get through; not a dual-squad league


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", [LeagueVisibility.OPEN, LeagueVisibility.INVITE_ONLY])
async def test_public_leagues_unchanged(client, db_session_factory, visibility):
    s = await _setup(db_session_factory, visibility)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    for path in GATED:
        url = _url(path, s)
        guest = (await client.get(url)).status_code
        assert guest == (401 if path in LOGIN_EVERYWHERE else 200), (url, guest)
        assert (await client.get(url, headers=stranger)).status_code == 200, url


@pytest.mark.asyncio
async def test_private_league_accepted_invitee_reads_everything(client, db_session_factory):
    s = await _setup(db_session_factory, LeagueVisibility.PRIVATE)
    invitee, invitee_id = await _user(db_session_factory)
    async with db_session_factory() as db:
        db.add(LeagueInvite(league_id=s["league"], token_hash=uuid.uuid4().hex, invited_email="i@t.local", status=InviteStatus.ACCEPTED, accepted_by_user_id=invitee_id,
                            expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
        await db.commit()
    _anon(client)
    for path in GATED:
        url = _url(path, s)
        r = await client.get(url, headers=invitee)
        assert r.status_code == 200, (url, r.status_code, r.text[:200])
