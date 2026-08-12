"""
Tests for commissioner.review_trade's roster compare-and-swap -- the
exact code an in-code comment describes having personally reproduced a
lost-update bug in, with zero automated coverage before this file. See
conftest.py's "Async DB + HTTP integration test infrastructure" section
for how `client`/`seed` work.

Note on approach: a genuinely concurrent asyncio.gather() test against
two real HTTP requests was tried first and dropped -- it produced
inconsistent results under the in-memory SQLite StaticPool setup (all
test sessions sharing one literal sqlite3 connection), which doesn't
faithfully reproduce production's real Postgres row locking and
transaction isolation, so a pass/fail there wouldn't actually mean
anything about the real guarantee. The tests below instead exercise the
CAS mechanism directly and deterministically: the exact
`UPDATE ... WHERE id = X AND roster_version = observed_version` pattern
review_trade uses, checking it does what it claims (rowcount 1 when the
observed version still matches, rowcount 0 -- not a silent overwrite --
when something else already changed it), plus the real endpoint's
happy-path behavior end to end.
"""
import uuid
import pytest
from sqlalchemy import select, update
from app.models.team import Team
from app.models.transaction import Transaction, TransactionType, TransactionStatus


async def _make_trade(db_session_factory, league_id, proposer_id, target_id, offered, requested):
    """Directly inserts a PENDING trade Transaction (bypassing the propose
    endpoint -- not what's under test here)."""
    async with db_session_factory() as db:
        trade = Transaction(
            id=str(uuid.uuid4()), league_id=league_id, team_id=proposer_id,
            type=TransactionType.TRADE, status=TransactionStatus.PENDING,
            details={
                "target_team_id": target_id,
                "offered_player_ids": offered,
                "requested_player_ids": requested,
            },
        )
        db.add(trade)
        await db.commit()
        return trade.id


@pytest.mark.asyncio
async def test_cas_update_succeeds_when_version_still_matches(seed):
    """The exact WHERE-clause pattern review_trade uses: an UPDATE
    conditioned on roster_version matching what was just observed should
    apply cleanly (rowcount 1) when nothing else has touched the row."""
    db_session_factory = seed["db_session_factory"]
    team_a = seed["team_a"]

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        team = result.scalar_one()
        observed_version = team.roster_version
        assert observed_version == 0

        cas = await db.execute(
            update(Team)
            .where(Team.id == team_a, Team.roster_version == observed_version)
            .values(roster=["new-roster"], roster_version=Team.roster_version + 1)
        )
        await db.commit()
        assert cas.rowcount == 1

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        team = result.scalar_one()
        assert team.roster == ["new-roster"]
        assert team.roster_version == 1


@pytest.mark.asyncio
async def test_cas_update_rejects_stale_version_instead_of_overwriting(seed):
    """The core guarantee: if roster_version has moved on since a caller
    observed it (another request/trade/waiver committed in between), the
    same WHERE-clause pattern must affect zero rows -- not silently
    overwrite whatever the concurrent write just applied. This is
    precisely what protects against the lost-update bug the real
    endpoint's comments describe having reproduced."""
    db_session_factory = seed["db_session_factory"]
    team_a = seed["team_a"]

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        team = result.scalar_one()
        observed_version = team.roster_version  # 0 -- what a caller "read" before acting

    # Simulate another request committing a roster change in between --
    # team_a's real current version is now 1, with a different roster.
    async with db_session_factory() as db:
        await db.execute(
            update(Team)
            .where(Team.id == team_a)
            .values(roster=["someone-elses-change"], roster_version=1)
        )
        await db.commit()

    # The original caller's CAS attempt, still using its now-stale
    # observed_version=0, must be rejected -- not apply on top of the
    # concurrent change.
    async with db_session_factory() as db:
        cas = await db.execute(
            update(Team)
            .where(Team.id == team_a, Team.roster_version == observed_version)
            .values(roster=["stale-callers-change"], roster_version=Team.roster_version + 1)
        )
        await db.commit()
        assert cas.rowcount == 0, "a stale roster_version must never match and overwrite"

    # Team A's roster must still be exactly what the concurrent write set
    # it to -- neither corrupted nor silently reverted.
    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        team = result.scalar_one()
        assert team.roster == ["someone-elses-change"]
        assert team.roster_version == 1


@pytest.mark.asyncio
async def test_review_trade_endpoint_approve_happy_path(client, seed):
    """End-to-end sanity check through the real endpoint: approving a
    single pending trade actually swaps the rosters and bumps
    roster_version, exactly once."""
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r.status_code == 200

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        final_a = result.scalar_one()
        result = await db.execute(select(Transaction).where(Transaction.id == trade_id))
        final_trade = result.scalar_one()

    assert a0 not in final_a.roster
    assert b0 in final_a.roster
    assert final_a.roster_version == 1
    assert final_trade.status == TransactionStatus.APPROVED


@pytest.mark.asyncio
async def test_review_trade_endpoint_rejects_already_reviewed_trade(client, seed):
    """A trade that's already been approved/denied can't be reviewed
    again -- confirms the endpoint's own guard, independent of the CAS
    layer underneath it."""
    league_id = seed["league_id"]
    team_a, team_b = seed["team_a"], seed["team_b"]
    a0, b0 = seed["players"][0], seed["players"][2]
    db_session_factory = seed["db_session_factory"]

    trade_id = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r1 = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r1.status_code == 200

    r2 = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_id}/review", json={"action": "approve"})
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_sequential_trades_on_the_same_team_both_succeed(client, seed):
    """Two trades on the same team, reviewed one after another (no actual
    race -- each request reads fresh state), should both apply cleanly,
    each bumping roster_version by 1. Confirms the CAS isn't over-strict
    about legitimate, non-conflicting sequential writes."""
    league_id = seed["league_id"]
    team_a, team_b, team_c = seed["team_a"], seed["team_b"], seed["team_c"]
    a0, a1, b0, c0 = seed["players"][0], seed["players"][1], seed["players"][2], seed["players"][4]
    db_session_factory = seed["db_session_factory"]

    trade_ab = await _make_trade(db_session_factory, league_id, team_a, team_b, [a0], [b0])
    trade_ac = await _make_trade(db_session_factory, league_id, team_a, team_c, [a1], [c0])

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r1 = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_ab}/review", json={"action": "approve"})
    r2 = await client.post(f"/leagues/{league_id}/commissioner/trades/{trade_ac}/review", json={"action": "approve"})

    assert r1.status_code == 200
    assert r2.status_code == 200

    async with db_session_factory() as db:
        result = await db.execute(select(Team).where(Team.id == team_a))
        final_a = result.scalar_one()

    assert set(final_a.roster) == {b0, c0}
    assert final_a.roster_version == 2
