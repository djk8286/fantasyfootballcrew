"""Concurrent lock-ordering checks on a real Postgres (SQLite ignores FOR
UPDATE). Skipped unless FFC_PG_TEST_URL points at a throwaway database
migrated to head, e.g.

    FFC_PG_TEST_URL=postgresql+asyncpg://user@localhost:5432/ffc_test pytest tests/test_seat_lock_ordering_pg.py

Each check has a control that removes the change and asserts the old
behaviour still shows up, so the check is known to discriminate."""
import asyncio
import collections
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import or_, select

from app.models.league import League, LeagueType, LeagueVisibility
from app.models.league_invite import InviteStatus, LeagueInvite
from app.models.team import Team
from app.models.transaction import Transaction
from app.services.auth_service import hash_token
from tests.test_draft_queue import _make_user
from tests.test_trade_respond import _propose, _respond, _review, _set_league_type, _set_team, _setup

PG_URL = os.environ.get("FFC_PG_TEST_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set FFC_PG_TEST_URL to a throwaway Postgres to run")
RUNS = 5


@pytest_asyncio.fixture
async def db_session_factory():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.limiter import limiter
    limiter.enabled = False
    engine = create_async_engine(PG_URL, pool_size=20, max_overflow=10)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        limiter.enabled = True


def _outcome(x):
    if isinstance(x, BaseException):
        return f"{type(x).__name__}: {'deadlock' if 'deadlock' in str(x).lower() else str(x).splitlines()[0][:60]}"
    return x.status_code


async def _set_league(f, league_id, **fields):
    async with f() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        for k, v in fields.items():
            setattr(league, k, v)
        await db.commit()


# ─── Trade approval vs claim-co-owner ───────────────────────────────────

async def _approve_vs_claim_co_owner(client, f, monkeypatch):
    """Approval pauses just before it writes notifications; claim-co-owner
    on one of the trading teams starts meanwhile."""
    import app.api.v1.commissioner as cm
    out = collections.Counter()
    for _ in range(RUNS):
        s = await _setup(f)
        lid = s["league"].id
        await _set_league_type(f, lid, LeagueType.TWO_MAN)
        await _set_league(f, lid, visibility=LeagueVisibility.OPEN)
        await _set_team(f, s["teams"][1].id, co_owner_id=None)
        trade = await _propose(client, s)
        assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200

        paused, resume = asyncio.Event(), asyncio.Event()
        orig = cm.notify_team_owners
        first = {"v": True}

        async def gated(*a, **k):
            if first["v"]:
                first["v"] = False
                paused.set()
                await resume.wait()
            return await orig(*a, **k)

        monkeypatch.setattr(cm, "notify_team_owners", gated)

        async def claim_while_paused():
            await paused.wait()
            task = asyncio.create_task(
                client.post(f"/teams/{s['teams'][1].id}/claim-co-owner", headers=s["h"]["out"]))
            await asyncio.sleep(0.5)
            resume.set()
            return await task

        approve, claim = await asyncio.wait_for(
            asyncio.gather(_review(client, s, trade["id"]), claim_while_paused(), return_exceptions=True), 30)
        monkeypatch.setattr(cm, "notify_team_owners", orig)
        async with f() as db:
            status = (await db.execute(select(Transaction.status).where(Transaction.id == trade["id"]))).scalar_one().value
        out[(_outcome(approve), _outcome(claim), status)] += 1
    return out


@pytest.mark.asyncio
async def test_pg_approve_and_claim_co_owner_do_not_deadlock(client, db_session_factory, monkeypatch):
    out = await _approve_vs_claim_co_owner(client, db_session_factory, monkeypatch)
    print("\nwith league-first approve:", dict(out))
    assert out == {(200, 200, "approved"): RUNS}


@pytest.mark.asyncio
async def test_pg_control_without_league_lock_on_approve(client, db_session_factory, monkeypatch):
    import app.api.v1.commissioner as cm

    async def no_lock(db, league_id, *teams):
        return None

    monkeypatch.setattr(cm, "lock_league_seats", no_lock)
    out = await _approve_vs_claim_co_owner(client, db_session_factory, monkeypatch)
    print("\ncontrol (approve without league lock):", dict(out))
    assert any("deadlock" in str(k) for k in out), out


# ─── Two people accepting one invite ────────────────────────────────────

async def _double_accept(client, f, monkeypatch):
    import app.api.v1.invites as inv_mod
    orig_lock = inv_mod.lock_league_seats

    async def lock_after_both_read(db, league_id, *teams):
        await asyncio.sleep(0.2)  # both requests have read the invite as pending
        await orig_lock(db, league_id, *teams)

    monkeypatch.setattr(inv_mod, "lock_league_seats", lock_after_both_read)
    out = collections.Counter()
    for _ in range(RUNS):
        s = await _setup(f)
        lid = s["league"].id
        await _set_league(f, lid, visibility=LeagueVisibility.PRIVATE)
        await _set_team(f, s["teams"][1].id, owner_id=None, co_owner_id=None, is_cpu=True)
        raw = uuid.uuid4().hex
        async with f() as db:
            db.add(LeagueInvite(league_id=lid, invited_email="friend@test.local", invited_by_user_id=s["commish"].id,
                                token_hash=hash_token(raw), status=InviteStatus.PENDING,
                                expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
            await db.commit()
        _, other_token = await _make_user(f)
        a, b = await asyncio.wait_for(asyncio.gather(
            client.post(f"/invites/{raw}/accept", headers=s["h"]["out"]),
            client.post(f"/invites/{raw}/accept", headers={"Authorization": f"Bearer {other_token}"}),
            return_exceptions=True), 30)
        async with f() as db:
            claimed = len((await db.execute(select(Team.id).where(
                Team.league_id == lid, Team.is_cpu == False, Team.owner_id != s["commish"].id))).all())  # noqa: E712
        out[(tuple(sorted(str(_outcome(x)) for x in (a, b))), claimed)] += 1
    return out


@pytest.mark.asyncio
async def test_pg_invite_is_accepted_once(client, db_session_factory, monkeypatch):
    out = await _double_accept(client, db_session_factory, monkeypatch)
    print("\nwith invite lock + re-check:", dict(out))
    assert out == {(("200", "400"), 1): RUNS}


@pytest.mark.asyncio
async def test_pg_control_without_invite_recheck(client, db_session_factory, monkeypatch):
    import app.api.v1.invites as inv_mod

    async def no_recheck(db, invite):
        return invite

    monkeypatch.setattr(inv_mod, "_lock_pending_invite", no_recheck)
    out = await _double_accept(client, db_session_factory, monkeypatch)
    print("\ncontrol (no invite re-check):", dict(out))
    assert out.get((("200", "200"), 2), 0) > 0, out


# ─── Remove-owner vs the same person claiming another team ──────────────

async def _remove_vs_claim(client, f, monkeypatch, lock_on_remove=True):
    """The owner's team is eliminated (so it doesn't count as a live seat)
    and they claim a CPU team while the commissioner removes them from the
    eliminated one. Afterwards their seat and their invite must agree."""
    import app.api.v1.teams as teams_mod
    import app.services.team_claim_service as claim_mod
    orig_check, orig_lock = claim_mod.require_one_live_seat, teams_mod.lock_league_seats
    out = collections.Counter()
    for _ in range(RUNS):
        s = await _setup(f)
        lid = s["league"].id
        removed_from = s["teams"][1].id
        await _set_league(f, lid, visibility=LeagueVisibility.PRIVATE)
        await _set_team(f, removed_from, co_owner_id=None, eliminated_week=3)
        async with f() as db:
            owner_id = (await db.execute(select(Team.owner_id).where(Team.id == removed_from))).scalar_one()
            db.add(LeagueInvite(league_id=lid, invited_email="o@test.local", invited_by_user_id=s["commish"].id,
                                token_hash=hash_token(uuid.uuid4().hex), status=InviteStatus.ACCEPTED,
                                accepted_by_user_id=owner_id, accepted_at=datetime.now(timezone.utc),
                                expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
            await db.commit()

        async def slow_check(*a, **k):
            await orig_check(*a, **k)
            await asyncio.sleep(0.4)

        async def lock(db, league_id, *teams):
            if not lock_on_remove and teams and teams[0].id == removed_from:
                for t in teams:
                    await db.refresh(t)
                return
            await orig_lock(db, league_id, *teams)

        monkeypatch.setattr(claim_mod, "require_one_live_seat", slow_check)
        monkeypatch.setattr(teams_mod, "lock_league_seats", lock)

        async def remove_soon():
            await asyncio.sleep(0.15)
            return await client.post(f"/teams/{removed_from}/remove-owner", headers=s["h"]["commish"])

        claim, remove = await asyncio.wait_for(asyncio.gather(
            client.post(f"/teams/{s['teams'][2].id}/claim", headers=s["h"]["owner"]),
            remove_soon(), return_exceptions=True), 30)
        async with f() as db:
            seats = len((await db.execute(select(Team.id).where(
                Team.league_id == lid, or_(Team.owner_id == owner_id, Team.co_owner_id == owner_id)))).all())
            invite = (await db.execute(select(LeagueInvite.status).where(
                LeagueInvite.league_id == lid, LeagueInvite.accepted_by_user_id == owner_id))).scalar_one().value
        out[(_outcome(claim), _outcome(remove), seats, invite)] += 1
    return out


@pytest.mark.asyncio
async def test_pg_remove_owner_and_claim_leave_seat_and_invite_consistent(client, db_session_factory, monkeypatch):
    out = await _remove_vs_claim(client, db_session_factory, monkeypatch)
    print("\nwith league lock on remove-owner:", dict(out))
    assert out == {(200, 200, 1, "accepted"): RUNS}


@pytest.mark.asyncio
async def test_pg_control_without_league_lock_on_remove_owner(client, db_session_factory, monkeypatch):
    out = await _remove_vs_claim(client, db_session_factory, monkeypatch, lock_on_remove=False)
    print("\ncontrol (remove-owner without league lock):", dict(out))
    assert out.get((200, 200, 1, "revoked"), 0) > 0, out
