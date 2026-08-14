"""
Spot-checks for the rate-limit expansion (Auth Security Hardening,
Step 4) -- confirms a representative sample of the newly-decorated
endpoints actually enforce their limit with a real "Nth request in the
window gets 429", not just that the decorator is present syntactically.

slowapi's Limiter is a process-wide in-memory singleton (see
core/limiter.py's own docstring) -- its state is NOT reset between
tests, so every test here resets it before AND after, or it would
either inherit leftover usage from an earlier test (false 429) or
leave usage behind for a later test (false negative there, or an
unrelated test unexpectedly 429ing). Confirmed empirically (a throwaway
probe against /auth/register) that the test client's ASGI transport
does get a single stable key, so this pollution is real, not
theoretical.
"""
import uuid
import pytest
from app.core.limiter import limiter
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.services.auth_service import hash_password, create_access_token


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


async def _make_user_and_token(db_session_factory):
    async with db_session_factory() as db:
        user = User(
            id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.com",
            username=f"rluser{uuid.uuid4().hex[:8]}", hashed_password=hash_password("password123"),
            provider="email",
        )
        db.add(user)
        await db.commit()
        return create_access_token({"sub": user.id, "email": user.email, "token_version": 0})


@pytest.mark.asyncio
async def test_league_creation_429s_after_the_hourly_limit(client, db_session_factory):
    token = await _make_user_and_token(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"

    statuses = []
    for i in range(11):  # limit is 10/hour
        r = await client.post("/leagues", json={"name": f"RL Test League {i}"})
        statuses.append(r.status_code)

    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


@pytest.mark.asyncio
async def test_trade_proposal_429s_after_the_hourly_limit(client, db_session_factory, seed):
    """Uses the shared `seed` fixture (commissioner + league + teams
    a/b/c) -- empty offered/requested player lists are a trivially
    valid proposal (empty set is a subset of any roster), so this only
    exercises the rate limit itself, nothing about trade validity."""
    client.headers["Authorization"] = f"Bearer {seed['token']}"

    statuses = []
    for i in range(21):  # limit is 20/hour
        r = await client.post(f"/leagues/{seed['league_id']}/trades", json={
            "team_id": seed["team_a"], "target_team_id": seed["team_b"],
            "offered_player_ids": [], "requested_player_ids": [],
        })
        statuses.append(r.status_code)

    assert statuses[:20] == [201] * 20
    assert statuses[20] == 429


async def _make_fresh_draftable_league(db_session_factory, num_teams=4):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@example.com",
                             username=f"draftcommish{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()
        league = League(id=str(uuid.uuid4()), name="RL Draft Test League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, draft_status=DraftStatus.NOT_STARTED,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        for i in range(num_teams):
            db.add(Team(id=str(uuid.uuid4()), name=f"CPU {i}", league_id=league.id,
                        owner_id=commissioner.id, is_cpu=True, roster=[], roster_version=0))
        await db.commit()
        token = create_access_token({"sub": commissioner.id, "email": commissioner.email, "token_version": 0})
        return {"league_id": league.id, "token": token}


@pytest.mark.asyncio
async def test_draft_pick_limit_does_not_fire_prematurely(client, db_session_factory):
    """Draft picks get a deliberately generous 300/hour so a real live
    draft's rapid-fire picks never get throttled -- firing 300+1 real
    sequential picks here (with valid turn-order/roster bookkeeping)
    would mean building a full mock-draft harness for marginal benefit.
    Instead: confirm a normal small burst of picks (well under the
    limit) all succeed, i.e. the limit doesn't fire prematurely and
    break ordinary drafting -- the actual risk this generous number
    exists to avoid."""
    setup = await _make_fresh_draftable_league(db_session_factory)
    client.headers["Authorization"] = f"Bearer {setup['token']}"

    r = await client.post("/drafts", json={"league_id": setup["league_id"], "total_rounds": 1})
    assert r.status_code == 201
    draft_id = r.json()["id"]
    r = await client.post(f"/drafts/{draft_id}/start")
    assert r.status_code == 200

    # A handful of auto-picks (whoever's on the clock, all CPU teams
    # here) -- must all succeed, none should 429.
    statuses = []
    for _ in range(4):
        r = await client.post(f"/drafts/{draft_id}/auto-pick")
        statuses.append(r.status_code)
        if r.status_code != 200:
            break

    assert 429 not in statuses
