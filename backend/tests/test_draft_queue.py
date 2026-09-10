"""
Tests for the server-persisted draft pick queue and the timer-expiry
watchdog (2026-09-09):

- The queue survives a "page refresh" (it's DB-backed now, not React
  state) -- GET after POST add/remove reflects what was saved.
- Auto-pick (both the manual endpoint and the timer watchdog) takes from
  a team's queue FIRST, in order, before falling back to AI ranking.
- A drafted player is removed from every team's queue, not just the
  picking team's.
- The watchdog forces a pick once a draft's timer has genuinely expired,
  and leaves an unexpired draft alone.
"""
import uuid
import pytest
from datetime import datetime, timedelta, timezone
from app.models.user import User
from app.models.league import League, LeagueVisibility, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.draft import Draft, DraftPick, DraftRunStatus
from app.models.draft_queue_entry import DraftQueueEntry
from app.services.auth_service import create_access_token
from app.services.draft_manager import (
    add_to_queue, remove_from_queue, get_team_queue, get_next_pick_for_team,
    create_draft, start_draft, make_pick,
)


async def _make_user(db_session_factory, username=None):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=username or f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league_with_teams(db_session_factory, num_teams=4):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Queue Test League", commissioner_id=commissioner.id,
                         visibility=LeagueVisibility.OPEN, scoring_config={}, roster_slots={},
                         league_type=LeagueType.STANDARD, draft_status=DraftStatus.NOT_STARTED)
        db.add(league)
        teams = []
        for i in range(num_teams):
            t = Team(id=str(uuid.uuid4()), name=f"Team {i}", league_id=league.id,
                      owner_id=commissioner.id if i == 0 else None, is_cpu=(i != 0), roster=[])
            db.add(t)
            teams.append(t)
        await db.commit()
        for t in teams:
            await db.refresh(t)
        return league, teams, commissioner, commissioner_token


async def _make_players(db_session_factory, n=10, position="RB"):
    players = []
    async with db_session_factory() as db:
        for i in range(n):
            p = Player(id=f"p{position}{i}-{uuid.uuid4().hex[:6]}", sleeper_id=str(uuid.uuid4()),
                       first_name=f"Player{i}", last_name=position, position=position,
                       search_rank=i + 1)
            db.add(p)
            players.append(p)
        await db.commit()
        for p in players:
            await db.refresh(p)
    return players


@pytest.mark.asyncio
async def test_queue_add_get_remove_via_api(client, db_session_factory):
    league, teams, commissioner, commissioner_token = await _make_league_with_teams(db_session_factory, num_teams=2)
    players = await _make_players(db_session_factory, n=3)
    my_team = teams[0]

    client.headers["Authorization"] = f"Bearer {commissioner_token}"

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)

    r = await client.get(f"/drafts/{draft.id}/queue", params={"team_id": my_team.id})
    assert r.status_code == 200
    assert r.json()["player_ids"] == []

    r = await client.post(f"/drafts/{draft.id}/queue/add", json={"team_id": my_team.id, "player_id": players[0].id})
    assert r.status_code == 200
    r = await client.post(f"/drafts/{draft.id}/queue/add", json={"team_id": my_team.id, "player_id": players[1].id})
    assert r.status_code == 200

    # "Page refresh" -- a fresh GET reflects what was saved, in order.
    r = await client.get(f"/drafts/{draft.id}/queue", params={"team_id": my_team.id})
    assert r.json()["player_ids"] == [players[0].id, players[1].id]

    r = await client.post(f"/drafts/{draft.id}/queue/remove", json={"team_id": my_team.id, "player_id": players[0].id})
    assert r.status_code == 200
    r = await client.get(f"/drafts/{draft.id}/queue", params={"team_id": my_team.id})
    assert r.json()["player_ids"] == [players[1].id]


@pytest.mark.asyncio
async def test_queue_rejects_cpu_team(client, db_session_factory):
    league, teams, commissioner, commissioner_token = await _make_league_with_teams(db_session_factory, num_teams=2)
    players = await _make_players(db_session_factory, n=1)
    cpu_team = teams[1]

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)

    r = await client.post(f"/drafts/{draft.id}/queue/add", json={"team_id": cpu_team.id, "player_id": players[0].id})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_queue_rejects_non_owner(client, db_session_factory):
    league, teams, commissioner, _commissioner_token = await _make_league_with_teams(db_session_factory, num_teams=2)
    players = await _make_players(db_session_factory, n=1)
    outsider, outsider_token = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    r = await client.post(f"/drafts/{draft.id}/queue/add", json={"team_id": teams[0].id, "player_id": players[0].id})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_next_pick_for_team_prefers_queue_over_ai(db_session_factory):
    league, teams, commissioner, _token = await _make_league_with_teams(db_session_factory, num_teams=2)
    # A deliberately low-ranked (bad) player queued on purpose -- if the
    # queue is respected, this exact player comes back even though the
    # AI ranking would never pick them this early.
    bad_pick = (await _make_players(db_session_factory, n=1, position="K"))[0]
    good_players = await _make_players(db_session_factory, n=5, position="RB")

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)
        await add_to_queue(db, draft.id, teams[0].id, bad_pick.id)

        player = await get_next_pick_for_team(db, draft.id, teams[0].id)
        assert player is not None
        assert player.id == bad_pick.id


@pytest.mark.asyncio
async def test_get_next_pick_for_team_falls_back_to_ai_when_queue_empty(db_session_factory):
    league, teams, commissioner, _token = await _make_league_with_teams(db_session_factory, num_teams=2)
    await _make_players(db_session_factory, n=5, position="RB")

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)
        player = await get_next_pick_for_team(db, draft.id, teams[0].id)
        assert player is not None  # AI fallback returned someone


@pytest.mark.asyncio
async def test_get_next_pick_for_team_skips_already_drafted_queue_entries(db_session_factory):
    league, teams, commissioner, _token = await _make_league_with_teams(db_session_factory, num_teams=2)
    players = await _make_players(db_session_factory, n=3, position="RB")

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)
        # Queue two players on team 0; team order is randomized at
        # create_draft time, so drive picks entirely off draft.team_order
        # rather than assuming teams[0] picks first.
        await add_to_queue(db, draft.id, teams[0].id, players[0].id)
        await add_to_queue(db, draft.id, teams[0].id, players[1].id)

        import json as _json
        team_order = _json.loads(draft.team_order)
        first_team_id = team_order[0]
        # Someone else (or this same team, doesn't matter) drafts
        # players[0] first -- simulate by directly making that pick for
        # whichever team is actually first on the clock.
        await make_pick(db, draft.id, first_team_id, players[0].id)

        player = await get_next_pick_for_team(db, draft.id, teams[0].id)
        assert player is not None
        assert player.id == players[1].id  # skipped the now-drafted players[0]


@pytest.mark.asyncio
async def test_drafted_player_removed_from_every_teams_queue(db_session_factory):
    league, teams, commissioner, _token = await _make_league_with_teams(db_session_factory, num_teams=2)
    players = await _make_players(db_session_factory, n=2, position="RB")

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)
        # Both teams queue the SAME player.
        await add_to_queue(db, draft.id, teams[0].id, players[0].id)
        await add_to_queue(db, draft.id, teams[1].id, players[0].id)

        import json as _json
        team_order = _json.loads(draft.team_order)
        await make_pick(db, draft.id, team_order[0], players[0].id)

        remaining_0 = await get_team_queue(db, draft.id, teams[0].id)
        remaining_1 = await get_team_queue(db, draft.id, teams[1].id)
        assert remaining_0 == []
        assert remaining_1 == []


@pytest.mark.asyncio
async def test_timer_watchdog_forces_pick_on_expiry(db_session_factory, monkeypatch):
    import app.services.scheduler as scheduler_module
    # Same pattern the old draft-scheduling tests used: the watchdog
    # reads app.core.database.async_session directly (not the
    # FastAPI-overridable get_db dependency), so it needs its own
    # monkeypatch to see this test's isolated DB.
    monkeypatch.setattr(scheduler_module, "async_session", db_session_factory)

    league, teams, commissioner, _token = await _make_league_with_teams(db_session_factory, num_teams=2)
    await _make_players(db_session_factory, n=5, position="RB")

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)
        # Force the deadline into the past.
        result = await db.execute(
            __import__("sqlalchemy").select(Draft).where(Draft.id == draft.id)
        )
        d = result.scalar_one()
        d.current_pick_started_at = datetime.now(timezone.utc) - timedelta(seconds=d.timer_seconds + 30)
        await db.commit()

    await scheduler_module._process_expired_draft_picks_once()

    async with db_session_factory() as db:
        result = await db.execute(
            __import__("sqlalchemy").select(DraftPick).where(DraftPick.draft_id == draft.id)
        )
        picks = result.scalars().all()
        assert len(picks) == 1  # exactly one pick was auto-forced


@pytest.mark.asyncio
async def test_timer_watchdog_leaves_unexpired_draft_alone(db_session_factory, monkeypatch):
    import app.services.scheduler as scheduler_module
    monkeypatch.setattr(scheduler_module, "async_session", db_session_factory)

    league, teams, commissioner, _token = await _make_league_with_teams(db_session_factory, num_teams=2)
    await _make_players(db_session_factory, n=5, position="RB")

    async with db_session_factory() as db:
        draft = await create_draft(db, league.id, total_rounds=3)
        await start_draft(db, draft.id)
        # current_pick_started_at is "now" (just started) -- default
        # timer_seconds=60, nowhere near expiry.

    await scheduler_module._process_expired_draft_picks_once()

    async with db_session_factory() as db:
        result = await db.execute(
            __import__("sqlalchemy").select(DraftPick).where(DraftPick.draft_id == draft.id)
        )
        assert result.scalars().all() == []  # nothing forced -- timer hasn't expired
