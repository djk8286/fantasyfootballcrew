"""Draft room reliability (QA regression 2026-10-19).

- The server enforces the pick clock itself: an expired clock is
  autopicked whether the team's Autopick toggle is on or off, with no
  browser open, exactly once even with concurrent workers, and after a
  restart (fresh process caches, clock already expired).
- CPU teams (including pick 1 of a quickstarted mock) pick server-side.
- Autopick is server-persisted per team/draft and honoured by the server.
- Auto-Pick All / Sim to My Pick coexist with the watchdog (no 400 on a
  lost race, no duplicate picks).
- /state is cached, ETagged and gzip-able; /auto-pick and /pick are cheap.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base

from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.player import Player
from app.models.team import Team
from app.models.user import User
from app.services import draft_board
from app.services.auth_service import create_access_token
from app.services.draft_manager import make_pick, quickstart_mock_draft, run_mock_draft


async def _seed(factory, n_players=60):
    async with factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@t.local",
                    username=f"u{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        for i in range(n_players):
            pos = ["QB", "RB", "WR", "TE", "K", "DEF"][i % 6]
            db.add(Player(id=str(uuid.uuid4()), sleeper_id=str(uuid.uuid4()), first_name=f"P{i}",
                          last_name=pos, position=pos, team="KC", search_rank=i + 1))
        await db.commit()
        return user


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': user.id, 'email': user.email})}"}


@pytest.fixture
def watchdog(db_session_factory, monkeypatch):
    import app.services.scheduler as sched
    from app.core.config import settings
    monkeypatch.setattr(sched, "async_session", db_session_factory)
    monkeypatch.setattr(sched, "draft_session", db_session_factory)
    monkeypatch.setattr(settings, "CPU_PICK_DELAY_S", 0.0)
    return sched._process_expired_draft_picks_once


async def _backdate(factory, draft_id, seconds):
    async with factory() as db:
        d = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()
        d.current_pick_started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        await db.commit()


async def _picks(factory, draft_id):
    async with factory() as db:
        return (await db.execute(
            select(DraftPick).where(DraftPick.draft_id == draft_id).order_by(DraftPick.pick_number)
        )).scalars().all()


async def _draft(factory, draft_id):
    async with factory() as db:
        return (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()


def _assert_clean(picks):
    numbers = [p.pick_number for p in picks]
    assert numbers == list(range(1, len(picks) + 1)), numbers
    assert len({p.player_id for p in picks}) == len(picks)


@pytest.mark.asyncio
async def test_expired_clock_autopicks_with_autopick_off(db_session_factory, watchdog):
    """QA pick 18: Autopick Off, clock hit 0, draft stalled forever."""
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=1)
    # The human is on the clock first; not expired yet -> nothing happens.
    await watchdog()
    assert await _picks(db_session_factory, draft.id) == []
    # Clock runs out (60s default) with Autopick OFF and no tab open.
    await _backdate(db_session_factory, draft.id, seconds=61)
    await watchdog()
    picks = await _picks(db_session_factory, draft.id)
    assert len(picks) == 1 and picks[0].team_id == my_team and picks[0].pick_number == 1


@pytest_asyncio.fixture
async def file_db_factory(tmp_path):
    """A real file-backed SQLite DB with separate connections per session,
    so concurrent sessions get real transactions and real write locking
    (the shared StaticPool connection used elsewhere can't model a race)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}", connect_args={"timeout": 5})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_watchdogs_pick_exactly_once(file_db_factory, monkeypatch):
    """Three workers (e.g. old + new container during a deploy) hit the
    same expired clock at once: exactly one pick is recorded."""
    import app.services.scheduler as sched
    from app.core.config import settings
    monkeypatch.setattr(sched, "draft_session", file_db_factory)
    monkeypatch.setattr(sched, "async_session", file_db_factory)
    monkeypatch.setattr(settings, "CPU_PICK_DELAY_S", 0.0)
    user = await _seed(file_db_factory)
    async with file_db_factory() as db:
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=1)
    await _backdate(file_db_factory, draft.id, seconds=600)
    await asyncio.wait_for(asyncio.gather(*(sched._process_expired_draft_picks_once() for _ in range(3))), 30)
    picks = await _picks(file_db_factory, draft.id)
    assert len(picks) == 1
    _assert_clean(picks)


@pytest.mark.asyncio
async def test_restart_mid_draft_with_expired_clock(db_session_factory, watchdog):
    """Server restarts mid-draft while a human's clock runs out: the first
    tick after startup (cold caches, nothing in memory) makes that pick
    once and the draft carries on to completion."""
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=3, total_rounds=2, draft_position=3)
    for _ in range(2):  # the two CPU picks ahead of the human
        await watchdog()
    assert len(await _picks(db_session_factory, draft.id)) == 2

    draft_board.clear_caches()  # "restart": no process state survives
    await _backdate(db_session_factory, draft.id, seconds=3600)  # clock expired while down
    await watchdog()
    picks = await _picks(db_session_factory, draft.id)
    assert len(picks) == 3 and picks[2].team_id == my_team

    for _ in range(20):
        await _backdate(db_session_factory, draft.id, seconds=3600)
        await watchdog()
    d = await _draft(db_session_factory, draft.id)
    assert d.status == DraftRunStatus.COMPLETED
    picks = await _picks(db_session_factory, draft.id)
    assert len(picks) == 6
    _assert_clean(picks)


@pytest.mark.asyncio
async def test_mock_cpu_makes_pick_one_server_side(db_session_factory, watchdog):
    """QA BUG G: CPU Team on the clock for pick 1 never picked."""
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=2)
    await watchdog()
    picks = await _picks(db_session_factory, draft.id)
    assert len(picks) == 1 and picks[0].team_id != my_team


@pytest.mark.asyncio
async def test_watchdog_survives_exhausted_request_pool(db_session_factory, watchdog, monkeypatch):
    """The watchdog runs on its own pool: a dead request pool can't stall CPU picks."""
    import app.services.scheduler as sched

    class _Dead:
        async def __aenter__(self):
            raise TimeoutError("QueuePool limit reached")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(sched, "async_session", lambda: _Dead())
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=1, draft_position=4)
    await watchdog()
    assert len(await _picks(db_session_factory, draft.id)) == 1


@pytest.mark.asyncio
async def test_paused_draft_never_advances_even_when_expired(client, db_session_factory, watchdog):
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=1, draft_position=1)
    assert (await client.post(f"/drafts/{draft.id}/pause", headers=_auth(user))).status_code == 200
    await _backdate(db_session_factory, draft.id, seconds=600)
    await watchdog()
    assert await _picks(db_session_factory, draft.id) == []


@pytest.mark.asyncio
async def test_autopick_is_persisted_and_server_enforced(client, db_session_factory, watchdog):
    """QA BUG M: toggle reset to Off on reload. Now persisted per team/draft,
    and ON means the server picks for you immediately, tab or no tab."""
    user = await _seed(db_session_factory)
    h = _auth(user)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=1)

    r = await client.get(f"/drafts/{draft.id}/autopick", params={"team_id": my_team}, headers=h)
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = await client.put(f"/drafts/{draft.id}/autopick", json={"team_id": my_team, "enabled": True}, headers=h)
    assert r.status_code == 200 and r.json()["enabled"] is True
    # "Reload": a fresh GET still says on.
    r = await client.get(f"/drafts/{draft.id}/autopick", params={"team_id": my_team}, headers=h)
    assert r.json()["enabled"] is True

    # Clock NOT expired, but autopick is on -> the server picks now.
    await watchdog()
    picks = await _picks(db_session_factory, draft.id)
    assert len(picks) == 1 and picks[0].team_id == my_team

    # Toggle off again: idempotent upsert, and the server waits for the clock.
    r = await client.put(f"/drafts/{draft.id}/autopick", json={"team_id": my_team, "enabled": False}, headers=h)
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_autopick_is_owner_only(client, db_session_factory):
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        other = User(id=str(uuid.uuid4()), email="x@t.local", username="xuser", hashed_password="x")
        db.add(other)
        await db.commit()
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=1)
    r = await client.put(f"/drafts/{draft.id}/autopick", json={"team_id": my_team, "enabled": True}, headers=_auth(other))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_pick_number_makes_a_double_click_idempotent(db_session_factory):
    """Snake turn: the same team picks twice in a row; a double-submitted
    pick for the first must not land on the second."""
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=2, total_rounds=2, draft_position=2)
    async with db_session_factory() as db:
        order = json.loads((await db.execute(select(Draft).where(Draft.id == draft.id))).scalar_one().team_order)
        assert order[1] == order[2] == my_team
        players = (await db.execute(select(Player).order_by(Player.search_rank))).scalars().all()
        await make_pick(db, draft.id, order[0], players[0].id, expected_pick_number=1)
    async with db_session_factory() as db:
        await make_pick(db, draft.id, my_team, players[1].id, expected_pick_number=2)
    async with db_session_factory() as db:
        with pytest.raises(ValueError):
            await make_pick(db, draft.id, my_team, players[2].id, expected_pick_number=2)
    picks = await _picks(db_session_factory, draft.id)
    assert len(picks) == 2


@pytest.mark.asyncio
async def test_auto_pick_all_completes_while_watchdog_races(client, db_session_factory, watchdog, monkeypatch):
    """QA: Auto-Pick All had no visible effect -- the old loop 400'd on the
    first collision with the watchdog. Here the watchdog lands a pick in
    between the loop choosing a player and writing it, on every third
    pick: the loop must re-sync and finish the draft cleanly."""
    import app.services.draft_manager as dm
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=3, draft_position=2)

    real_choose = dm.get_ai_mock_pick
    calls = 0

    async def racing_choose(*a, **kw):
        nonlocal calls
        choice = await real_choose(*a, **kw)
        calls += 1
        if calls % 3 == 0:
            await watchdog()  # someone else picks first
        return choice

    monkeypatch.setattr(dm, "get_ai_mock_pick", racing_choose)
    resp = await client.post(f"/drafts/{draft.id}/mock", json={}, headers=_auth(user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"
    picks = await _picks(db_session_factory, draft.id)
    assert len(picks) == 12
    _assert_clean(picks)


@pytest.mark.asyncio
async def test_sim_to_my_pick_stops_at_my_turn(db_session_factory):
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=2, draft_position=3)
    async with db_session_factory() as db:
        made = await run_mock_draft(db, draft.id, skip_team_ids=[my_team])
    assert len(made) == 2
    picks = await _picks(db_session_factory, draft.id)
    assert all(p.team_id != my_team for p in picks)


@pytest.mark.asyncio
async def test_state_etag_gzip_and_invalidation(client, db_session_factory):
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=1, draft_position=1)
    r1 = await client.get(f"/drafts/{draft.id}/state", headers={"Accept-Encoding": "gzip"})
    assert r1.status_code == 200
    assert r1.headers.get("content-encoding") == "gzip"
    etag = r1.headers["etag"]
    body = r1.json()
    assert body["current_team_id"] == my_team
    assert body["available_players"] and "stats" not in body["available_players"][0]
    assert body["available_players"][0]["pos_rank"] == 1

    r304 = await client.get(f"/drafts/{draft.id}/state", headers={"If-None-Match": etag})
    assert r304.status_code == 304 and r304.content == b""

    r = await client.post(f"/drafts/{draft.id}/pick", headers=_auth(user),
                          json={"team_id": my_team, "player_id": body["available_players"][0]["id"], "pick_number": 1})
    assert r.status_code == 200, r.text
    assert r.json()["player"] == body["available_players"][0]["full_name"]

    r2 = await client.get(f"/drafts/{draft.id}/state", headers={"If-None-Match": etag})
    assert r2.status_code == 200 and r2.headers["etag"] != etag
    s2 = r2.json()
    assert len(s2["picks"]) == 1
    assert s2["picks"][0]["player"]["id"] == body["available_players"][0]["id"]
    assert all(p["id"] != body["available_players"][0]["id"] for p in s2["available_players"])


@pytest.mark.asyncio
async def test_concurrent_state_polls_share_one_build(client, db_session_factory, monkeypatch):
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, _ = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=1)
    import app.services.draft_manager as dm
    builds = 0
    real = dm._build_state

    async def counting(*a, **kw):
        nonlocal builds
        builds += 1
        return await real(*a, **kw)

    monkeypatch.setattr(dm, "_build_state", counting)
    rs = await asyncio.gather(*[client.get(f"/drafts/{draft.id}/state") for _ in range(8)])
    assert all(r.status_code == 200 for r in rs)
    assert len({r.headers["etag"] for r in rs}) == 1
    assert builds == 1


@pytest.mark.asyncio
async def test_auto_pick_endpoint_uses_cheap_lookup(client, db_session_factory, monkeypatch):
    user = await _seed(db_session_factory)
    async with db_session_factory() as db:
        draft, my_team = await quickstart_mock_draft(db, user.id, num_teams=4, total_rounds=1, draft_position=1)
    import app.services.draft_manager as dm

    async def boom(*a, **kw):
        raise AssertionError("auto-pick must not build the full draft state")

    monkeypatch.setattr(dm, "get_draft_state", boom)
    r = await client.post(f"/drafts/{draft.id}/auto-pick", headers=_auth(user))
    assert r.status_code == 200, r.text
    assert r.json()["team_id"] == my_team and r.json()["pick_number"] == 1
