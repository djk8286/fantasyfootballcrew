"""One player, one roster per league (QA 2026-10-19: Josh Allen was on
the QA team via an approved waiver claim and on Team 5, who drafted him).

Covers every roster-add path (waiver processing, draft picks and
autopick, the draft board) and the idempotent startup repair."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.contract import Contract
from app.models.draft import Draft, DraftPick
from app.models.player import Player
from app.models.team import Team
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.services import draft_board
from app.services.draft_manager import get_draft_state, get_next_pick_for_team, make_pick, quickstart_mock_draft
from app.services.roster_guard import PlayerAlreadyRostered
from app.services.roster_repair import repair_duplicate_rostered_players
from tests.test_draft_reliability import _seed as _seed_players


async def _claim(factory, league_id, team_id, add_id, drop_id=None, status=TransactionStatus.PENDING, at=None, details=None):
    async with factory() as db:
        c = Transaction(id=str(uuid.uuid4()), league_id=league_id, team_id=team_id, type=TransactionType.WAIVER,
                        status=status, details={"add_player_id": add_id, "drop_player_id": drop_id, **(details or {})})
        if at:
            c.processed_at = at
        db.add(c)
        await db.commit()
        return c.id


async def _set_roster(factory, team_id, roster):
    async with factory() as db:
        t = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one()
        t.roster = list(roster)
        t.roster_version = (t.roster_version or 0) + 1
        await db.commit()


async def _team(factory, team_id):
    async with factory() as db:
        return (await db.execute(select(Team).where(Team.id == team_id))).scalar_one()


async def _tx(factory, tx_id):
    async with factory() as db:
        return (await db.execute(select(Transaction).where(Transaction.id == tx_id))).scalar_one()


# ─── Waivers ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_claim_for_player_rostered_after_submission_is_denied(client, seed):
    """The prod case: claim filed while the player was free; someone else
    rostered him before processing."""
    f, lid = seed["db_session_factory"], seed["league_id"]
    star = str(uuid.uuid4())
    claim_id = await _claim(f, lid, seed["team_a"], star)
    b = await _team(f, seed["team_b"])
    await _set_roster(f, seed["team_b"], [*b.roster, star])  # e.g. drafted by Team B

    client.headers["Authorization"] = f"Bearer {seed['token']}"
    r = await client.post(f"/leagues/{lid}/waivers/process")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["granted"] == []
    assert body["denied"][0]["add_player_id"] == star
    assert "Team B" in body["denied"][0]["reason"]
    assert star not in (await _team(f, seed["team_a"])).roster
    assert (await _tx(f, claim_id)).status == TransactionStatus.DENIED


@pytest.mark.asyncio
async def test_claim_for_player_already_on_own_roster_is_denied(client, seed):
    f, lid = seed["db_session_factory"], seed["league_id"]
    a0 = seed["players"][0]
    await _claim(f, lid, seed["team_a"], a0)
    client.headers["Authorization"] = f"Bearer {seed['token']}"
    body = (await client.post(f"/leagues/{lid}/waivers/process")).json()
    assert body["granted"] == [] and len(body["denied"]) == 1
    assert (await _team(f, seed["team_a"])).roster.count(a0) == 1


@pytest.mark.asyncio
async def test_multi_round_run_never_puts_one_player_on_two_rosters(client, seed):
    """Rolling rounds (#22): team A's second claim and team B's claim both
    want the player team A gets in round one, plus a dropped player can be
    re-claimed by someone else in a later round."""
    f, lid = seed["db_session_factory"], seed["league_id"]
    a0 = seed["players"][0]
    x, y = str(uuid.uuid4()), str(uuid.uuid4())
    t0 = datetime.now(timezone.utc) - timedelta(hours=1)
    await _claim(f, lid, seed["team_a"], x, drop_id=a0, at=t0)
    await _claim(f, lid, seed["team_a"], y, at=t0 + timedelta(minutes=1))
    await _claim(f, lid, seed["team_b"], x, at=t0 + timedelta(minutes=2))
    await _claim(f, lid, seed["team_c"], y, at=t0 + timedelta(minutes=3))
    await _claim(f, lid, seed["team_b"], a0, at=t0 + timedelta(minutes=4))  # a0 freed by team A's drop
    client.headers["Authorization"] = f"Bearer {seed['token']}"
    body = (await client.post(f"/leagues/{lid}/waivers/process")).json()

    async with f() as db:
        teams = (await db.execute(select(Team).where(Team.league_id == lid))).scalars().all()
    every = [pid for t in teams for pid in (t.roster or [])]
    assert len(every) == len(set(every))
    holders = {pid: t.id for t in teams for pid in t.roster}
    assert holders[x] == seed["team_a"]
    assert holders[a0] == seed["team_b"]
    assert y in holders
    assert all(g["add_player_id"] for g in body["granted"])


@pytest.mark.asyncio
async def test_granted_claim_records_grant_time(client, seed):
    f, lid = seed["db_session_factory"], seed["league_id"]
    claim_id = await _claim(f, lid, seed["team_a"], str(uuid.uuid4()))
    client.headers["Authorization"] = f"Bearer {seed['token']}"
    await client.post(f"/leagues/{lid}/waivers/process")
    assert (await _tx(f, claim_id)).details["granted_at"]


# ─── Draft ──────────────────────────────────────────────────────────────

async def _draft_with_rostered_player(factory):
    """A 2-team, 2-round draft where the best-ranked player was already
    added to the CPU team's roster (as a waiver mid-draft would)."""
    user = await _seed_players(factory)
    async with factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=2, total_rounds=2, draft_position=1)
    async with factory() as db:
        d = (await db.execute(select(Draft).where(Draft.id == draft.id))).scalar_one()
        order = json.loads(d.team_order)
        cpu = next(t for t in order if t != my_team)
        players = (await db.execute(select(Player).order_by(Player.search_rank))).scalars().all()
    await _set_roster(factory, cpu, [players[0].id])
    return draft, my_team, cpu, players


@pytest.mark.asyncio
async def test_draft_pick_of_a_rostered_player_is_refused_and_changes_nothing(db_session_factory):
    f = db_session_factory
    draft, my_team, cpu, players = await _draft_with_rostered_player(f)
    async with f() as db:
        with pytest.raises(PlayerAlreadyRostered):
            await make_pick(db, draft.id, my_team, players[0].id, expected_pick_number=1)
    async with f() as db:
        d = (await db.execute(select(Draft).where(Draft.id == draft.id))).scalar_one()
        assert (d.current_round, d.current_pick) == (1, 1)
        assert (await db.execute(select(DraftPick).where(DraftPick.draft_id == draft.id))).first() is None
    assert players[0].id not in ((await _team(f, my_team)).roster or [])
    # A free player is still fine.
    async with f() as db:
        await make_pick(db, draft.id, my_team, players[1].id, expected_pick_number=1)
    assert players[1].id in (await _team(f, my_team)).roster


@pytest.mark.asyncio
async def test_autopick_and_board_skip_rostered_players(db_session_factory):
    f = db_session_factory
    draft_board.clear_caches()
    draft, my_team, cpu, players = await _draft_with_rostered_player(f)
    async with f() as db:
        from app.services.draft_manager import add_to_queue
        await add_to_queue(db, draft.id, my_team, players[0].id)
        await add_to_queue(db, draft.id, my_team, players[2].id)
        await db.commit()
    async with f() as db:
        nxt = await get_next_pick_for_team(db, draft.id, my_team)
        assert nxt.id == players[2].id
    async with f() as db:
        from app.models.draft_queue_entry import DraftQueueEntry
        await db.execute(DraftQueueEntry.__table__.delete())
        await db.commit()
    async with f() as db:
        nxt = await get_next_pick_for_team(db, draft.id, my_team, current_round=1, total_rounds=2)
        assert nxt is not None and nxt.id != players[0].id
    async with f() as db:
        state = await get_draft_state(db, draft.id)
    assert players[0].id not in {p["id"] for p in state["available_players"]}


# ─── Startup repair ─────────────────────────────────────────────────────

async def _league_dupe(factory, *, with_contract=False):
    """Team 5 drafted the star; the QA team was later granted an old
    waiver claim for him (filed before the pick, no granted_at)."""
    user = await _seed_players(factory)
    async with factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=2, total_rounds=1, draft_position=1)
    async with factory() as db:
        d = (await db.execute(select(Draft).where(Draft.id == draft.id))).scalar_one()
        cpu = next(t for t in json.loads(d.team_order) if t != my_team)
        star = (await db.execute(select(Player).order_by(Player.search_rank))).scalars().first()
    t_claim = datetime.now(timezone.utc) - timedelta(days=2)
    async with factory() as db:
        db.add(DraftPick(id=str(uuid.uuid4()), draft_id=draft.id, league_id=d.league_id, team_id=cpu, player_id=star.id, round=1,
                         pick_number=2, drafted_at=t_claim + timedelta(minutes=30)))
        await db.commit()
    claim_id = await _claim(factory, d.league_id, my_team, star.id, status=TransactionStatus.APPROVED, at=t_claim)
    await _set_roster(factory, cpu, [star.id])
    await _set_roster(factory, my_team, ["keep-1", star.id])
    if with_contract:
        async with factory() as db:
            db.add(Contract(league_id=d.league_id, team_id=my_team, player_id=star.id, salary=5, contract_years=2,
                            signed_year=2026, source="waiver", is_active=True))
            await db.commit()
    return d.league_id, my_team, cpu, star.id, claim_id


@pytest.mark.asyncio
async def test_repair_keeps_the_drafting_team_and_voids_the_later_waiver_add(db_session_factory):
    f = db_session_factory
    lid, qa_team, team5, star, claim_id = await _league_dupe(f, with_contract=True)
    before = (await _team(f, qa_team)).roster_version
    async with f() as db:
        changes = await repair_duplicate_rostered_players(db)
    assert [(c["player_id"], c["removed_from"], c["kept_on"]) for c in changes] == [(star, qa_team, team5)]
    qa = await _team(f, qa_team)
    assert qa.roster == ["keep-1"] and qa.roster_version == before + 1
    assert (await _team(f, team5)).roster == [star]
    assert "already on" in (await _tx(f, claim_id)).details["voided"]
    async with f() as db:
        c = (await db.execute(select(Contract).where(Contract.team_id == qa_team))).scalar_one()
        assert c.is_active is False
    # Idempotent.
    async with f() as db:
        assert await repair_duplicate_rostered_players(db) == []


@pytest.mark.asyncio
async def test_repair_trade_beats_waiver_and_earlier_grant_wins_between_waivers(client, seed):
    f, lid = seed["db_session_factory"], seed["league_id"]
    p, q = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    # p: team_b received him in an approved trade; team_a has a waiver grant.
    async with f() as db:
        db.add(Transaction(league_id=lid, team_id=seed["team_c"], type=TransactionType.TRADE,
                           status=TransactionStatus.APPROVED, processed_at=now - timedelta(days=3),
                           details={"target_team_id": seed["team_b"], "offered_player_ids": [p], "requested_player_ids": []}))
        await db.commit()
    await _claim(f, lid, seed["team_a"], p, status=TransactionStatus.APPROVED, at=now - timedelta(days=5),
                 details={"granted_at": (now - timedelta(days=1)).isoformat()})
    # q: two waiver grants; team_c's was granted first.
    await _claim(f, lid, seed["team_c"], q, status=TransactionStatus.APPROVED, at=now - timedelta(days=2),
                 details={"granted_at": (now - timedelta(hours=10)).isoformat()})
    await _claim(f, lid, seed["team_a"], q, status=TransactionStatus.APPROVED, at=now - timedelta(days=4),
                 details={"granted_at": (now - timedelta(hours=5)).isoformat()})
    a, b, c = (await _team(f, seed["team_a"])), (await _team(f, seed["team_b"])), (await _team(f, seed["team_c"]))
    await _set_roster(f, seed["team_a"], [*a.roster, p, q, a.roster[0]])  # also a self-duplicate
    await _set_roster(f, seed["team_b"], [*b.roster, p])
    await _set_roster(f, seed["team_c"], [*c.roster, q])
    async with f() as db:
        changes = await repair_duplicate_rostered_players(db)
    kept = {ch["player_id"]: ch["kept_on"] for ch in changes if ch["player_id"]}
    assert kept == {p: seed["team_b"], q: seed["team_c"]}
    a2 = await _team(f, seed["team_a"])
    assert p not in a2.roster and q not in a2.roster and len(a2.roster) == len(set(a2.roster)) == 2
    async with f() as db:
        assert await repair_duplicate_rostered_players(db) == []


@pytest.mark.asyncio
async def test_roster_adds_take_the_league_row_lock(client, seed, db_session_factory, monkeypatch):
    """Both add paths lock the league row (FOR UPDATE on Postgres) before
    reading rosters, so two adds in one league are serialized."""
    from sqlalchemy.dialects import postgresql
    from app.services import roster_guard, waiver_service
    from app.models.league import League

    stmt = select(League.id).where(League.id == "x").with_for_update()
    assert "FOR UPDATE" in str(stmt.compile(dialect=postgresql.dialect()))

    locked = []
    real = roster_guard.lock_league_rosters

    async def spy(db, league_id):
        locked.append(league_id)
        await real(db, league_id)

    monkeypatch.setattr(waiver_service, "lock_league_rosters", spy)
    monkeypatch.setattr(roster_guard, "lock_league_rosters", spy)
    client.headers["Authorization"] = f"Bearer {seed['token']}"
    await client.post(f"/leagues/{seed['league_id']}/waivers/process")
    assert locked == [seed["league_id"]]

    draft, my_team, cpu, players = await _draft_with_rostered_player(db_session_factory)
    async with db_session_factory() as db:
        league_id = (await db.execute(select(Draft.league_id).where(Draft.id == draft.id))).scalar_one()
        await make_pick(db, draft.id, my_team, players[1].id, expected_pick_number=1)
    assert locked[-1] == league_id
