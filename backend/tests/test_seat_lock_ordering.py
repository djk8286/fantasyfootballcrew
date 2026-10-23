"""Lock ordering and consistency for seat changes, trade approval, invite
acceptance and co-commissioner removal. Every path that locks the league
row takes it first, before trade, team or invite rows. SQLite ignores
FOR UPDATE, so these tests record the order the locks are requested in;
tests/test_seat_lock_ordering_pg.py runs the concurrent cases on Postgres."""
import contextlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.api.v1 import invites as invites_mod
from app.models.league import League, LeagueType, LeagueVisibility
from app.models.league_invite import InviteStatus, LeagueInvite
from app.models.team import Team
from app.models.transaction import Transaction, TransactionStatus
from app.services.auth_service import hash_token
from tests.test_draft_queue import _make_user
from tests.test_trade_respond import _propose, _respond, _review, _set_team, _setup, _team


@contextlib.contextmanager
def lock_log():
    """Tables of every SELECT ... FOR UPDATE, in the order they're issued."""
    seen = []

    def on_execute(state):
        stmt = state.statement
        if state.is_select and getattr(stmt, "_for_update_arg", None) is not None:
            seen.append(stmt.get_final_froms()[0].name)

    event.listen(Session, "do_orm_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(Session, "do_orm_execute", on_execute)


async def _set_league(f, league_id, **fields):
    async with f() as db:
        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        for k, v in fields.items():
            setattr(league, k, v)
        await db.commit()


async def _league(f, league_id):
    async with f() as db:
        return (await db.execute(select(League).where(League.id == league_id))).scalar_one()


def _commish_action(client, s, action, user_id):
    return client.post(f"/leagues/{s['league'].id}/commissioner", headers=s["h"]["commish"],
                       json={"action": action, "user_id": user_id})


async def _accepted_trade(client, s):
    trade = await _propose(client, s)  # commissioner's team 0 -> owner's team 1
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200
    return trade


# ─── 1. Trade approval takes the league lock first ──────────────────────

@pytest.mark.asyncio
async def test_approve_locks_league_then_trade_then_teams(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _accepted_trade(client, s)
    with lock_log() as seen:
        r = await _review(client, s, trade["id"])
    assert r.status_code == 200, r.text
    assert seen == ["leagues", "transactions", "teams", "teams"]


@pytest.mark.asyncio
async def test_deny_is_unchanged(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _propose(client, s)
    with lock_log() as seen:
        r = await _review(client, s, trade["id"], "deny")
    assert r.status_code == 200
    assert seen == ["transactions"]


@pytest.mark.asyncio
async def test_approve_sees_co_commissioners_current_at_lock_time(client, db_session_factory, monkeypatch):
    """The commissioner set is re-read after the league lock, so a change
    committed while the approval waited for the lock is respected."""
    import app.api.v1.commissioner as cm
    f = db_session_factory
    s = await _setup(f)
    trade = await _accepted_trade(client, s)
    helper, _ = await _make_user(f)
    orig = cm.lock_league_seats

    async def add_co_commish_then_lock(db, league_id, *teams):
        await _set_league(f, league_id, co_commissioner_ids=[helper.id])  # lands before the lock
        await orig(db, league_id, *teams)

    monkeypatch.setattr(cm, "lock_league_seats", add_co_commish_then_lock)
    r = await _review(client, s, trade["id"])
    assert r.status_code == 400
    assert "another commissioner has to approve it" in r.json()["detail"]


# ─── 2. Removals and deletes take the league lock first ─────────────────

@pytest.mark.asyncio
async def test_remove_owner_locks_league_first(client, db_session_factory):
    s = await _setup(db_session_factory)
    with lock_log() as seen:
        r = await client.post(f"/teams/{s['teams'][1].id}/remove-owner", headers=s["h"]["commish"])
    assert r.status_code == 200
    assert seen[:1] == ["leagues"]


@pytest.mark.asyncio
async def test_remove_co_owner_locks_league_first(client, db_session_factory):
    s = await _setup(db_session_factory)
    with lock_log() as seen:
        r = await client.post(f"/teams/{s['teams'][1].id}/remove-co-owner", headers=s["h"]["commish"])
    assert r.status_code == 200
    assert seen[:1] == ["leagues"]
    assert (await _team(db_session_factory, s["teams"][1].id)).co_owner_id is None


@pytest.mark.asyncio
async def test_delete_team_locks_league_first(client, db_session_factory):
    s = await _setup(db_session_factory)
    with lock_log() as seen:
        r = await client.delete(f"/teams/{s['teams'][2].id}", headers=s["h"]["commish"])
    assert r.status_code == 204
    assert seen[:1] == ["leagues"]


@pytest.mark.asyncio
async def test_removals_still_require_a_commissioner(client, db_session_factory):
    s = await _setup(db_session_factory)
    with lock_log() as seen:
        assert (await client.post(f"/teams/{s['teams'][1].id}/remove-owner", headers=s["h"]["out"])).status_code == 403
        assert (await client.post(f"/teams/{s['teams'][1].id}/remove-co-owner", headers=s["h"]["out"])).status_code == 403
        assert (await client.delete(f"/teams/{s['teams'][2].id}", headers=s["h"]["out"])).status_code == 403
    assert seen == []  # no lock taken for a caller who isn't allowed


# ─── 3. An invite is accepted once ──────────────────────────────────────

async def _invite(f, league_id, inviter_id):
    raw = uuid.uuid4().hex
    async with f() as db:
        inv = LeagueInvite(league_id=league_id, invited_email="friend@test.local", invited_by_user_id=inviter_id,
                           token_hash=hash_token(raw), status=InviteStatus.PENDING,
                           expires_at=datetime.now(timezone.utc) + timedelta(days=7))
        db.add(inv)
        await db.commit()
        return raw, inv.id


@pytest.mark.asyncio
async def test_accept_invite_locks_league_then_invite(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    await _set_league(f, s["league"].id, visibility=LeagueVisibility.PRIVATE)
    raw, _ = await _invite(f, s["league"].id, s["commish"].id)
    with lock_log() as seen:
        r = await client.post(f"/invites/{raw}/accept", headers=s["h"]["out"])
    assert r.status_code == 200
    assert r.json()["claimed_team_id"] == s["teams"][2].id
    assert seen[:2] == ["leagues", "league_invites"]


@pytest.mark.asyncio
async def test_invite_accepted_while_waiting_for_the_lock_is_refused(client, db_session_factory, monkeypatch):
    """Two people open the same link. The first one's acceptance commits
    while the second waits on the league lock; the second gets a 400 and
    no team."""
    f = db_session_factory
    s = await _setup(f)
    await _set_league(f, s["league"].id, visibility=LeagueVisibility.PRIVATE)
    await _set_team(f, s["teams"][1].id, owner_id=None, co_owner_id=None, is_cpu=True)
    raw, invite_id = await _invite(f, s["league"].id, s["commish"].id)
    first, _ = await _make_user(f)
    orig = invites_mod.lock_league_seats

    async def someone_else_accepts_first(db, league_id, *teams):
        async with f() as other:
            inv = (await other.execute(select(LeagueInvite).where(LeagueInvite.id == invite_id))).scalar_one()
            inv.status, inv.accepted_by_user_id = InviteStatus.ACCEPTED, first.id
            inv.accepted_at = datetime.now(timezone.utc)
            await other.commit()
        await orig(db, league_id, *teams)

    monkeypatch.setattr(invites_mod, "lock_league_seats", someone_else_accepts_first)
    r = await client.post(f"/invites/{raw}/accept", headers=s["h"]["out"])
    assert (r.status_code, r.json()["detail"]) == (400, "This invite is no longer valid")
    async with f() as db:
        inv = (await db.execute(select(LeagueInvite).where(LeagueInvite.id == invite_id))).scalar_one()
        out_id = (await db.execute(select(Team.id).where(Team.league_id == s["league"].id,
                                                          Team.is_cpu == False))).scalars().all()  # noqa: E712
    assert inv.accepted_by_user_id == first.id
    assert len(out_id) == 1  # only the commissioner's team; nobody claimed a CPU team


@pytest.mark.asyncio
async def test_invite_revoked_while_waiting_for_the_lock_is_refused(client, db_session_factory, monkeypatch):
    f = db_session_factory
    s = await _setup(f)
    await _set_league(f, s["league"].id, visibility=LeagueVisibility.PRIVATE)
    raw, invite_id = await _invite(f, s["league"].id, s["commish"].id)
    orig = invites_mod.lock_league_seats

    async def revoked_first(db, league_id, *teams):
        async with f() as other:
            (await other.execute(select(LeagueInvite).where(LeagueInvite.id == invite_id))).scalar_one().status = InviteStatus.REVOKED
            await other.commit()
        await orig(db, league_id, *teams)

    monkeypatch.setattr(invites_mod, "lock_league_seats", revoked_first)
    r = await client.post(f"/invites/{raw}/accept", headers=s["h"]["out"])
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_revoke_invite_locks_league_then_invite(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    _, invite_id = await _invite(f, s["league"].id, s["commish"].id)
    with lock_log() as seen:
        r = await client.delete(f"/leagues/{s['league'].id}/invites/{invite_id}", headers=s["h"]["commish"])
    assert r.status_code == 200
    assert seen == ["leagues", "league_invites"]


# ─── 4. Co-commissioner removal while a trade awaits review ─────────────

AWAITING = ("A trade involving your team is waiting for commissioner review. "
            "Approve or deny it before removing a co-commissioner.")
SELF_APPROVE = "You manage a team in this trade, so another commissioner has to approve it"


@pytest.mark.asyncio
async def test_cannot_remove_co_commissioner_while_own_accepted_trade_awaits_review(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, helper_token = await _make_user(f)
    assert (await _commish_action(client, s, "add_co_commish", helper.id)).status_code == 200
    trade = await _accepted_trade(client, s)

    # The commissioner is in the trade and an uninvolved co-commissioner exists.
    r = await _review(client, s, trade["id"])
    assert r.status_code == 400 and "another commissioner" in r.json()["detail"]

    with lock_log() as seen:
        r = await _commish_action(client, s, "remove_co_commish", helper.id)
    assert (r.status_code, r.json()["detail"]) == (400, AWAITING)
    assert seen == ["leagues"]
    assert (await _league(f, s["league"].id)).co_commissioner_ids == [helper.id]

    # The uninvolved co-commissioner approves; then removal works.
    r = await client.post(f"/leagues/{s['league'].id}/commissioner/trades/{trade['id']}/review",
                          headers={"Authorization": f"Bearer {helper_token}"}, json={"action": "approve"})
    assert r.status_code == 200
    r = await _commish_action(client, s, "remove_co_commish", helper.id)
    assert r.status_code == 200 and r.json()["co_commissioner_ids"] == []


@pytest.mark.asyncio
async def test_removal_allowed_after_deny_or_before_acceptance(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, _ = await _make_user(f)
    await _commish_action(client, s, "add_co_commish", helper.id)

    # Offered, not accepted yet: removal isn't blocked, but the trade keeps
    # needing a commissioner outside it, so it can only be denied now.
    trade = await _propose(client, s)
    assert trade["details"]["needs_independent_approver"] is True
    assert (await _commish_action(client, s, "remove_co_commish", helper.id)).status_code == 200
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200
    r = await _review(client, s, trade["id"], "approve")
    assert (r.status_code, r.json()["detail"]) == (400, SELF_APPROVE)
    assert (await _review(client, s, trade["id"], "deny")).status_code == 200

    await _commish_action(client, s, "add_co_commish", helper.id)
    trade = await _accepted_trade(client, s)
    assert (await _review(client, s, trade["id"], "deny")).status_code == 200
    assert (await _commish_action(client, s, "remove_co_commish", helper.id)).status_code == 200


@pytest.mark.asyncio
async def test_propose_remove_accept_then_self_approve_is_refused(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, _ = await _make_user(f)
    await _commish_action(client, s, "add_co_commish", helper.id)
    trade = await _propose(client, s)
    assert (await _commish_action(client, s, "remove_co_commish", helper.id)).status_code == 200
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200

    r = await _review(client, s, trade["id"], "approve")
    assert (r.status_code, r.json()["detail"]) == (400, SELF_APPROVE)
    async with f() as db:
        row = (await db.execute(select(Transaction).where(Transaction.id == trade["id"]))).scalar_one()
        assert row.status == TransactionStatus.PENDING
    # Cancelling is still possible.
    r = await client.post(f"/leagues/{s['league'].id}/trades/{trade['id']}/cancel", headers=s["h"]["commish"])
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_flagged_trade_can_be_approved_by_a_commissioner_outside_it(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, helper_token = await _make_user(f)
    other, _ = await _make_user(f)
    await _commish_action(client, s, "add_co_commish", helper.id)
    trade = await _propose(client, s)
    assert (await _commish_action(client, s, "remove_co_commish", helper.id)).status_code == 200
    await _commish_action(client, s, "add_co_commish", other.id)
    await _commish_action(client, s, "add_co_commish", helper.id)
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200
    r = await client.post(f"/leagues/{s['league'].id}/commissioner/trades/{trade['id']}/review",
                          headers={"Authorization": f"Bearer {helper_token}"}, json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_flag_is_set_at_accept_when_an_outside_commissioner_appears(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    trade = await _propose(client, s)  # sole commissioner, seated in the trade
    assert "needs_independent_approver" not in trade["details"]
    helper, _ = await _make_user(f)
    await _commish_action(client, s, "add_co_commish", helper.id)
    r = await _respond(client, s, trade["id"], "owner", "accept")
    assert r.status_code == 200
    assert r.json()["details"]["needs_independent_approver"] is True


@pytest.mark.asyncio
async def test_older_trade_without_flag_uses_the_live_rule(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, _ = await _make_user(f)
    await _commish_action(client, s, "add_co_commish", helper.id)
    trade = await _propose(client, s)
    assert (await _commish_action(client, s, "remove_co_commish", helper.id)).status_code == 200
    assert (await _respond(client, s, trade["id"], "owner", "accept")).status_code == 200
    async with f() as db:  # a trade written before the flag existed
        row = (await db.execute(select(Transaction).where(Transaction.id == trade["id"]))).scalar_one()
        row.details = {k: v for k, v in row.details.items() if k != "needs_independent_approver"}
        await db.commit()
    r = await _review(client, s, trade["id"], "approve")
    assert r.status_code == 200, r.text

    # ... and with an outside commissioner present, the live rule still refuses.
    s = await _setup(f)
    trade = await _accepted_trade(client, s)
    async with f() as db:
        row = (await db.execute(select(Transaction).where(Transaction.id == trade["id"]))).scalar_one()
        row.details = {k: v for k, v in row.details.items() if k != "needs_independent_approver"}
        await db.commit()
    await _commish_action(client, s, "add_co_commish", helper.id)
    r = await _review(client, s, trade["id"], "approve")
    assert (r.status_code, r.json()["detail"]) == (400, SELF_APPROVE)


@pytest.mark.asyncio
async def test_league_locks_are_no_key_update(client, db_session_factory):
    """League locks are FOR NO KEY UPDATE so child-row inserts (which take a
    KEY SHARE lock on the league) aren't blocked by them."""
    from sqlalchemy.dialects import postgresql
    from app.services.team_seats import lock_league_seats
    from app.services.roster_guard import lock_league_rosters
    seen = []

    def on_execute(state):
        stmt = state.statement
        if state.is_select and getattr(stmt, "_for_update_arg", None) is not None \
                and stmt.get_final_froms()[0].name == "leagues":
            seen.append(str(stmt.compile(dialect=postgresql.dialect())))

    s = await _setup(db_session_factory)
    event.listen(Session, "do_orm_execute", on_execute)
    try:
        async with db_session_factory() as db:
            await lock_league_seats(db, s["league"].id)
            await lock_league_rosters(db, s["league"].id)
        trade = await _accepted_trade(client, s)
        assert (await _review(client, s, trade["id"], "approve")).status_code == 200
        await client.post(f"/teams/bulk-add/{s['league'].id}", headers=s["h"]["commish"], json={"count": 1})
        r = await client.patch(f"/leagues/{s['league'].id}", headers=s["h"]["commish"], json={"name": "Renamed"})
        assert r.status_code == 200, r.text
    finally:
        event.remove(Session, "do_orm_execute", on_execute)
    assert len(seen) >= 5, seen
    assert all("FOR NO KEY UPDATE" in q for q in seen), seen


@pytest.mark.asyncio
async def test_removal_allowed_when_accepted_trade_does_not_involve_the_remover(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, _ = await _make_user(f)
    await _commish_action(client, s, "add_co_commish", helper.id)
    # Owner's team 1 offers to CPU team 2; the CPU accepts. The commissioner isn't in it.
    r = await client.post(f"/leagues/{s['league'].id}/trades", headers=s["h"]["owner"],
                          json={"team_id": s["teams"][1].id, "target_team_id": s["teams"][2].id,
                                "offered_player_ids": [s["ps"][2].id], "requested_player_ids": []})
    assert r.status_code == 201 and r.json()["details"]["cpu_response"] == "accepted"
    assert (await _commish_action(client, s, "remove_co_commish", helper.id)).status_code == 200


@pytest.mark.asyncio
async def test_cpu_accepted_trade_with_remover_counts_as_awaiting(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, _ = await _make_user(f)
    await _commish_action(client, s, "add_co_commish", helper.id)
    r = await client.post(f"/leagues/{s['league'].id}/trades", headers=s["h"]["commish"],
                          json={"team_id": s["teams"][0].id, "target_team_id": s["teams"][2].id,
                                "offered_player_ids": [s["ps"][0].id], "requested_player_ids": []})
    assert r.json()["details"]["cpu_response"] == "accepted"
    r = await _commish_action(client, s, "remove_co_commish", helper.id)
    assert (r.status_code, r.json()["detail"]) == (400, AWAITING)


@pytest.mark.asyncio
async def test_sole_commissioner_can_still_approve_own_trade(client, db_session_factory):
    s = await _setup(db_session_factory)
    trade = await _accepted_trade(client, s)
    r = await _review(client, s, trade["id"])
    assert r.status_code == 200
    async with db_session_factory() as db:
        assert (await db.execute(select(Transaction.status).where(Transaction.id == trade["id"]))).scalar_one() \
            == TransactionStatus.APPROVED


@pytest.mark.asyncio
async def test_add_and_transfer_are_unaffected_by_a_pending_trade(client, db_session_factory):
    f = db_session_factory
    s = await _setup(f)
    helper, _ = await _make_user(f)
    await _accepted_trade(client, s)
    assert (await _commish_action(client, s, "add_co_commish", helper.id)).status_code == 200
    r = await _commish_action(client, s, "remove_co_commish", str(uuid.uuid4()))
    assert r.status_code == 404  # unknown user, checked before anything else
