"""
Tests for waivers.process_waivers -- previously zero coverage despite
using the exact same roster_version compare-and-swap pattern as
review_trade (see that endpoint's own comment: "same roster_version
compare-and-swap commissioner.review_trade uses, and for the same
reason"). The CAS mechanism itself (does the UPDATE...WHERE clause
correctly reject a stale version instead of overwriting) is already
proven deterministically in test_trade_concurrency.py against the
identical SQL pattern -- not re-proven here. What's waiver-specific and
actually needs its own coverage is the business logic layered on top of
it: priority order, conflicting claims for the same player, and the
"skip and leave PENDING for retry" behavior on a CAS miss (as opposed to
review_trade's "reject with 409").
"""
import uuid
import pytest
from sqlalchemy import select
from app.models.team import Team
from app.models.league import League
from app.models.transaction import Transaction, TransactionType, TransactionStatus


async def _make_claim(db_session_factory, league_id, team_id, add_id, drop_id=None):
    async with db_session_factory() as db:
        claim = Transaction(
            id=str(uuid.uuid4()), league_id=league_id, team_id=team_id,
            type=TransactionType.WAIVER, status=TransactionStatus.PENDING,
            details={"add_player_id": add_id, "drop_player_id": drop_id},
        )
        db.add(claim)
        await db.commit()
        return claim.id


@pytest.mark.asyncio
async def test_process_waivers_grants_a_valid_claim(client, seed):
    """Single pending claim, nothing contesting it -- should be granted,
    roster updated, roster_version bumped, team pushed to the back of
    the priority queue."""
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    a0 = seed["players"][0]  # already on team_a's roster
    free_agent = str(uuid.uuid4())  # not seeded onto any roster -- a real add target
    db_session_factory = seed["db_session_factory"]

    claim_id = await _make_claim(db_session_factory, league_id, team_a, free_agent, drop_id=a0)

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()
    assert len(body["granted"]) == 1
    assert body["granted"][0]["team_id"] == team_a

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        team = result.scalar_one()
        result = await db.execute(select(Transaction).where(Transaction.id == claim_id))
        claim = result.scalar_one()

    assert a0 not in team.roster
    assert free_agent in team.roster
    assert team.roster_version == 1
    assert claim.status == TransactionStatus.APPROVED
    # team_a moved to the back -- team_b now leads priority.
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
    assert league.waiver_priority[-1] == team_a


@pytest.mark.asyncio
async def test_two_teams_claiming_the_same_player_only_higher_priority_wins(client, seed):
    """team_a and team_b both claim the same free agent. Default priority
    is team creation order (team_a created first -- see _priority_order),
    so team_a should win and team_b's claim should be denied, not both
    granted (which would put the same player on two rosters)."""
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    contested_player = str(uuid.uuid4())
    db_session_factory = seed["db_session_factory"]

    claim_a = await _make_claim(db_session_factory, league_id, team_a, contested_player)
    claim_b = await _make_claim(db_session_factory, league_id, team_b, contested_player)

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()

    assert len(body["granted"]) == 1
    assert body["granted"][0]["team_id"] == team_a
    assert len(body["denied"]) == 1
    assert body["denied"][0]["team_id"] == team_b

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        team_a_obj = result.scalar_one()
        result = await db.execute(select(Team).where(Team.id == team_b))
        team_b_obj = result.scalar_one()
        result = await db.execute(select(Transaction).where(Transaction.id == claim_b))
        claim_b_obj = result.scalar_one()

    assert contested_player in team_a_obj.roster
    assert contested_player not in team_b_obj.roster
    assert claim_b_obj.status == TransactionStatus.DENIED


@pytest.mark.asyncio
async def test_claim_denied_when_drop_player_already_gone_from_roster(client, seed):
    """A claim asking to drop a player who's no longer actually on the
    roster (e.g. traded away since the claim was submitted) must be
    denied, not silently processed with a nonsense roster state."""
    league_id = seed["league_id"]
    team_a = seed["team_a"]
    already_gone = str(uuid.uuid4())  # never actually on team_a's roster
    free_agent = str(uuid.uuid4())
    db_session_factory = seed["db_session_factory"]

    claim_id = await _make_claim(db_session_factory, league_id, team_a, free_agent, drop_id=already_gone)

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200
    body = r.json()

    assert body["granted"] == []
    assert len(body["denied"]) == 1

    async with db_session_factory() as db:
        result = await db.execute(select(Transaction).where(Transaction.id == claim_id))
        claim = result.scalar_one()
        result = await db.execute(select(Team).where(Team.id == team_a))
        team = result.scalar_one()

    assert claim.status == TransactionStatus.DENIED
    assert free_agent not in team.roster  # never applied
    assert team.roster_version == 0  # no write attempted at all


@pytest.mark.asyncio
async def test_process_waivers_is_commissioner_only(client, seed):
    """Confirmed real authorization, not bypassed by the test setup --
    a non-commissioner user must be rejected."""
    league_id = seed["league_id"]
    async with seed["db_session_factory"]() as db:
        from app.models.user import User
        from app.services.auth_service import create_access_token
        outsider = User(id=str(uuid.uuid4()), email="outsider@test.local", username="outsider", hashed_password="x")
        db.add(outsider)
        await db.commit()
        outsider_token = create_access_token({"sub": outsider.id, "email": outsider.email})

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 403
