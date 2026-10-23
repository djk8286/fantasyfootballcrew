"""QA 2026-10-21: a PRIVATE league is members-only on EVERY read, not just
rosters and lineups (standings were public). deps.require_league_view /
require_team_league_view / require_draft_league_view apply #35's rule:
guest 401, logged-in non-member 403, members, commissioner and accepted
invitees 200. OPEN and INVITE_ONLY leagues are unchanged.

test_every_league_scoped_operation_is_gated_in_a_private_league walks
every operation in app.openapi() that takes a league, team, draft or trade
id (path or query, any method), so a new one can't ship ungated without a
reviewed entry in EXCEPTIONS."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from app.models.draft import Draft
from app.models.league import LeagueVisibility
from app.models.league_invite import InviteStatus, LeagueInvite
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.services.message_service import MESSAGE_TYPES
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

async def _setup(f, visibility):
    s = await _league(f, visibility)
    async with f() as db:
        d = Draft(id=str(uuid.uuid4()), league_id=s["league"], current_round=1, current_pick=1,
                  team_order=json.dumps([s["team"]]))
        trade = Transaction(league_id=s["league"], team_id=s["team"], type=TransactionType.TRADE,
                            status=TransactionStatus.PENDING, details={})
        db.add_all([d, trade])
        await db.commit()
    s["draft"] = d.id
    s["trade"] = trade.id
    s["player"] = s["players"][3]
    return s


def _url(path, s):
    return path.format(league=s["league"], team=s["team"], draft=s["draft"], player=s["player"])


# Every operation (any method) that takes one of these, in the path or the
# query, is walked below against a PRIVATE league.
SCOPED = {"league_id", "team_id", "draft_id", "trade_id", "available_in_league"}
# Reads that need more than membership (commissioner, the caller's own
# team, admin): the commissioner/owner gets through, the plain member may not.
STRICTER = {
    "/leagues/{league_id}/members", "/leagues/{league_id}/invites", "/leagues/{league_id}/join-requests",
    "/leagues/{league_id}/commissioner/digest", "/leagues/{league_id}/commissioner/health",
    "/leagues/{league_id}/commissioner/insights", "/leagues/{league_id}/commissioner/schedule-insights",
    "/leagues/{league_id}/commissioner/chat", "/drafts/{draft_id}/autopick", "/drafts/{draft_id}/queue",
}
# Reviewed exceptions to "guest 401, stranger 403/404, members get in".
# (METHOD, path) -> (guest statuses, stranger statuses, why).
EXCEPTIONS = {
    ("GET", "/ai/history"): ({401}, {200}, "only ever returns the caller's own analyses; league_id narrows them"),
    ("GET", "/admin/leagues/{league_id}"): ({401}, {403}, "admin only, so members are refused too"),
    ("DELETE", "/admin/leagues/{league_id}"): ({401}, {403}, "admin only"),
    ("POST", "/leagues/{league_id}/join-requests"): (
        {401}, {400}, "a stranger asking to join is the point; private leagues refuse with 400 and no league data"),
}
# Bodies _example can't guess: the route validates message_type before its access check.
BODIES = {
    ("POST", "/leagues/{league_id}/commissioner/messages/draft"): {"message_type": next(iter(MESSAGE_TYPES))},
    ("POST", "/leagues/{league_id}/commissioner/messages/send"): {"message_type": next(iter(MESSAGE_TYPES)), "content": "x"},
}
# Values for required query params the walk doesn't scope on.
FILLED = {"week": 7, "year": 2026, "analysis_type": "lineup"}


def _example(schema, components):
    """Smallest body FastAPI will accept for `schema`, so the walk reaches
    the route's own access check instead of stopping at a 422."""
    if "$ref" in schema:
        return _example(components[schema["$ref"].rsplit("/", 1)[1]], components)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"]
            return _example(options[0], components) if options else None
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    kind = schema.get("type")
    if kind == "object":
        return {k: _example(v, components) for k, v in schema.get("properties", {}).items()
                if k in schema.get("required", [])}
    if kind == "array":
        return [_example(schema["items"], components)] if schema.get("minItems") else []
    if kind == "integer":
        return max(schema.get("minimum", 1), 1)
    if kind == "number":
        return float(max(schema.get("minimum", 1), 1))
    if kind == "boolean":
        return False
    return str(uuid.uuid4())


def _scoped_operations():
    """(method, path, path_params, query, body) for every operation that
    takes a league/team/draft/trade id. An optional scoped query param gets
    its own request so each one is checked on its own.

    Blind spots: ids sent only in a request body aren't scoped, so
    /ai/trade (trade_id) and /ai/player-comparison (league_id) rely on
    their own checks. A stranger's 404 counts as refused, so the walk can't
    tell an access check from a lookup that simply missed."""
    spec = app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    for raw_path, ops in spec["paths"].items():
        path = raw_path.removeprefix("/api/v1")
        for method, op in ops.items():
            params = op.get("parameters", [])
            names = {p["name"] for p in params}
            if not names & SCOPED:
                continue
            content = op.get("requestBody", {}).get("content", {}).get("application/json")
            body = BODIES.get((method.upper(), path)) or (_example(content["schema"], components) if content else None)
            required_query = {p["name"] for p in params if p["in"] == "query" and p.get("required")}
            optional_scoped = {p["name"] for p in params if p["in"] == "query" and not p.get("required")} & SCOPED
            path_scoped = {p["name"] for p in params if p["in"] == "path"} & SCOPED
            variants = [set()] if path_scoped or required_query & SCOPED else []
            variants += [{q} for q in sorted(optional_scoped)]
            for extra in variants:
                yield method.upper(), path, {p["name"] for p in params if p["in"] == "path"}, required_query | extra, body


def _ids(s):
    return {"league_id": s["league"], "available_in_league": s["league"], "team_id": s["team"],
            "draft_id": s["draft"], "trade_id": s["trade"], "player_id": s["player"]}


def _request(method, path, path_params, query, body, s):
    ids = _ids(s)
    url = path.format(**{name: ids.get(name, str(uuid.uuid4())) for name in path_params})
    return {"method": method, "url": url, "params": {q: ids.get(q, FILLED.get(q, "x")) for q in sorted(query)},
            **({"json": body} if body is not None else {})}


def test_walk_covers_writes_and_query_scoped_routes():
    walked = {(m, p, tuple(sorted(q))) for m, p, _, q, _ in _scoped_operations()}
    for expected in [("POST", "/teams/{team_id}/news/generate", ()), ("GET", "/players", ("league_id",)),
                     ("GET", "/players/{player_id}", ("league_id",)), ("GET", "/players/{player_id}/detail", ("league_id",)),
                     ("GET", "/players", ("available_in_league",)), ("GET", "/drafts/find", ("league_id",)),
                     ("GET", "/leagues/{league_id}/trades", ("team_id",))]:
        assert expected in walked, expected
    operations = {(m, p) for m, p, *_ in walked}
    assert set(EXCEPTIONS) <= operations, set(EXCEPTIONS) - operations
    assert STRICTER <= {p for m, p in operations if m == "GET"}


@pytest.mark.asyncio
async def test_every_league_scoped_operation_is_gated_in_a_private_league(client, db_session_factory):
    """Guest 401 and logged-in stranger 403/404 on every operation SCOPED
    names, any method; members get through every read. An operation that
    isn't gated fails here until it's fixed or listed in EXCEPTIONS."""
    s = await _setup(db_session_factory, LeagueVisibility.PRIVATE)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    failures = []
    for method, path, path_params, query, body in _scoped_operations():
        req = _request(method, path, path_params, query, body, s)
        guest_ok, stranger_ok, _ = EXCEPTIONS.get((method, path), ({401}, {403, 404}, ""))
        label = f"{method} {path} {sorted(query)}"
        guest = (await client.request(**req)).status_code
        if guest not in guest_ok:
            failures.append(f"{label}: guest {guest}")
        outsider = (await client.request(**req, headers=stranger)).status_code
        if outsider not in stranger_ok:
            failures.append(f"{label}: stranger {outsider}")
        if method != "GET" or (method, path) in EXCEPTIONS:
            continue
        for who in ("owner",) if path in STRICTER else ("owner", "member"):
            status = (await client.request(**req, headers=s[who])).status_code
            if status in (401, 403):
                failures.append(f"{label}: {who} {status}")
    assert not failures, "\n".join(failures)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", list(LeagueVisibility))
async def test_news_generate_is_for_the_leagues_own_people(client, db_session_factory, visibility):
    """It spends AI budget, so a logged-in stranger is refused even in an OPEN league."""
    s = await _setup(db_session_factory, visibility)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    url = f"/teams/{s['team']}/news/generate"
    assert (await client.post(url)).status_code == 401
    assert (await client.post(url, headers=stranger)).status_code == 403
    for who in ("owner", "member"):
        r = await client.post(url, headers=s[who])
        assert r.status_code == 200, (who, r.text[:200])
        assert r.json()["team_id"] == s["team"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/players?league_id={league}", "/players/{player}?league_id={league}",
                                  "/players/{player}/detail?league_id={league}"])
async def test_player_reads_apply_a_private_leagues_scoring_only_for_members(client, db_session_factory, path):
    s = await _setup(db_session_factory, LeagueVisibility.PRIVATE)
    stranger, _ = await _user(db_session_factory)
    _anon(client)
    url = _url(path, s)
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=stranger)).status_code == 403
    assert (await client.get(url, headers=s["member"])).status_code == 200
    unknown = (await client.get(_url(path.replace("{league}", str(uuid.uuid4())), s))).status_code
    assert unknown == 200, "an unknown league_id still falls back to default scoring"


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", [LeagueVisibility.OPEN, LeagueVisibility.INVITE_ONLY])
async def test_player_reads_with_a_public_leagues_scoring_stay_public(client, db_session_factory, visibility):
    s = await _setup(db_session_factory, visibility)
    _anon(client)
    for path in ("/players?league_id={league}", "/players/{player}?league_id={league}", "/players/{player}/detail?league_id={league}"):
        assert (await client.get(_url(path, s))).status_code == 200, path
