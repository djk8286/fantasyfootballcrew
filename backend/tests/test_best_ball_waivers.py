"""
Tests for Best-Ball's waiver-processing management-window gate + the
scheduler's auto-process-on-window-reopen pass (Phase 6 Step 7).
Window settings are built from the REAL clock (no mocking) -- see
test_best_ball_trades.py's _closed_settings/_open_settings for the
case-analysis proof these are always correct for is_window_open.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.notification import Notification, NotificationType
from app.services.auth_service import create_access_token
from app.services.scheduler import _process_all_league_best_ball_window_reopens_once, _best_ball_window_state


def _closed_settings(now: datetime) -> dict:
    future = now + timedelta(hours=3)
    return {
        "enabled": True,
        "lock_weekday": now.weekday(), "lock_hour": now.hour,
        "reopen_weekday": future.weekday(), "reopen_hour": future.hour,
    }


def _open_settings(now: datetime) -> dict:
    future = now + timedelta(hours=3)
    return {
        "enabled": True,
        "lock_weekday": future.weekday(), "lock_hour": future.hour,
        "reopen_weekday": now.weekday(), "reopen_hour": now.hour,
    }


async def _make_league(db_session_factory, best_ball_settings=None):
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                             username=f"bbwcommish{uuid.uuid4().hex[:6]}", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(
            id=str(uuid.uuid4()), name="Best Ball Waivers Test League", commissioner_id=commissioner.id,
            league_type=LeagueType.STANDARD, draft_status=DraftStatus.COMPLETED,
            scoring_config={}, roster_slots={}, best_ball_settings=best_ball_settings,
        )
        db.add(league)
        await db.flush()

        team = Team(id=str(uuid.uuid4()), name="Only Team", league_id=league.id,
                    owner_id=commissioner.id, roster=[], roster_version=0)
        db.add(team)
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})
        return {"token": token, "commissioner_id": commissioner.id, "league_id": league.id,
                "team_id": team.id, "db_session_factory": db_session_factory}


async def _make_free_agent(db_session_factory):
    async with db_session_factory() as db:
        player = Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-bbw-{uuid.uuid4().hex[:8]}",
                         first_name="Free", last_name="Agent", position="RB")
        db.add(player)
        await db.commit()
        return player.id


async def _make_claim(db_session_factory, league_id, team_id, add_id):
    async with db_session_factory() as db:
        claim = Transaction(id=str(uuid.uuid4()), league_id=league_id, team_id=team_id,
                             type=TransactionType.WAIVER, status=TransactionStatus.PENDING,
                             details={"add_player_id": add_id, "drop_player_id": None})
        db.add(claim)
        await db.commit()
        return claim.id


async def _get_claim(db_session_factory, claim_id):
    async with db_session_factory() as db:
        return (await db.execute(select(Transaction).where(Transaction.id == claim_id))).scalar_one()


@pytest.fixture(autouse=True)
def _reset_window_state():
    """The scheduler's own module-level edge-detection dict -- must not
    leak league-id state between tests (each test creates a fresh
    league.id, but clearing defensively keeps this file order-independent)."""
    _best_ball_window_state.clear()
    yield
    _best_ball_window_state.clear()


@pytest.fixture(autouse=True)
def _use_test_db_for_scheduler(monkeypatch, db_session_factory):
    """_process_all_league_best_ball_window_reopens_once manages its own
    DB session via the module-level `async_session` (same pattern every
    other scheduler pass uses -- see test_scheduler.py's own docstring
    on why the rest of scheduler.py isn't unit-tested this way normally).
    db_session_factory is itself an async_sessionmaker with an identical
    interface, so swapping it in here is a faithful redirect to this
    test's isolated SQLite DB, not a behavior change."""
    monkeypatch.setattr("app.services.scheduler.async_session", db_session_factory)


@pytest.mark.asyncio
async def test_first_observation_does_not_fire_even_if_open(db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_league(db_session_factory, best_ball_settings=_open_settings(now))
    add_id = await _make_free_agent(db_session_factory)
    claim_id = await _make_claim(db_session_factory, setup["league_id"], setup["team_id"], add_id)

    await _process_all_league_best_ball_window_reopens_once(now=now)

    claim = await _get_claim(db_session_factory, claim_id)
    assert claim.status == TransactionStatus.PENDING
    assert _best_ball_window_state[setup["league_id"]] is True


@pytest.mark.asyncio
async def test_fires_on_closed_to_open_transition(db_session_factory):
    league_id = None
    now = datetime.now(timezone.utc)
    setup = await _make_league(db_session_factory, best_ball_settings=_closed_settings(now))
    league_id = setup["league_id"]
    add_id = await _make_free_agent(db_session_factory)
    claim_id = await _make_claim(db_session_factory, league_id, setup["team_id"], add_id)

    # Tick 1: observe closed (no-op, first observation).
    await _process_all_league_best_ball_window_reopens_once(now=now)
    claim = await _get_claim(db_session_factory, claim_id)
    assert claim.status == TransactionStatus.PENDING

    # Flip the league's own settings to open, then tick again -- the
    # transition (False -> True) should auto-process the queued claim.
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.best_ball_settings = _open_settings(now)
        await db.commit()

    await _process_all_league_best_ball_window_reopens_once(now=now)

    claim = await _get_claim(db_session_factory, claim_id)
    assert claim.status == TransactionStatus.APPROVED
    assert claim.reviewed_by is None  # scheduler-triggered, no human actor


@pytest.mark.asyncio
async def test_auto_process_fires_notification(db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_league(db_session_factory, best_ball_settings=_closed_settings(now))
    league_id = setup["league_id"]
    add_id = await _make_free_agent(db_session_factory)
    await _make_claim(db_session_factory, league_id, setup["team_id"], add_id)

    await _process_all_league_best_ball_window_reopens_once(now=now)
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.best_ball_settings = _open_settings(now)
        await db.commit()
    await _process_all_league_best_ball_window_reopens_once(now=now)

    async with db_session_factory() as db:
        result = await db.execute(
            select(Notification).where(
                Notification.user_id == setup["commissioner_id"],
                Notification.type == NotificationType.WAIVER_APPROVED,
            )
        )
        notifications = result.scalars().all()
    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_idempotent_across_repeated_open_ticks(db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_league(db_session_factory, best_ball_settings=_closed_settings(now))
    league_id = setup["league_id"]
    add_id = await _make_free_agent(db_session_factory)
    claim_id = await _make_claim(db_session_factory, league_id, setup["team_id"], add_id)

    await _process_all_league_best_ball_window_reopens_once(now=now)
    async with db_session_factory() as db:
        result = await db.execute(select(League).where(League.id == league_id))
        league = result.scalar_one()
        league.best_ball_settings = _open_settings(now)
        await db.commit()
    await _process_all_league_best_ball_window_reopens_once(now=now)  # fires

    # A second free agent claim submitted while still open -- a repeated
    # "still open" tick must NOT auto-process it (only the closed->open
    # EDGE triggers processing, not every open tick).
    add_id_2 = await _make_free_agent(db_session_factory)
    claim_id_2 = await _make_claim(db_session_factory, league_id, setup["team_id"], add_id_2)
    await _process_all_league_best_ball_window_reopens_once(now=now)

    claim_2 = await _get_claim(db_session_factory, claim_id_2)
    assert claim_2.status == TransactionStatus.PENDING


@pytest.mark.asyncio
async def test_manual_process_blocked_when_window_closed(client, db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_league(db_session_factory, best_ball_settings=_closed_settings(now))
    league_id = setup["league_id"]
    add_id = await _make_free_agent(db_session_factory)
    claim_id = await _make_claim(db_session_factory, league_id, setup["team_id"], add_id)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 400
    assert "management window is currently closed" in r.json()["detail"]

    claim = await _get_claim(db_session_factory, claim_id)
    assert claim.status == TransactionStatus.PENDING


@pytest.mark.asyncio
async def test_manual_process_works_when_window_open(client, db_session_factory):
    now = datetime.now(timezone.utc)
    setup = await _make_league(db_session_factory, best_ball_settings=_open_settings(now))
    league_id = setup["league_id"]
    add_id = await _make_free_agent(db_session_factory)
    claim_id = await _make_claim(db_session_factory, league_id, setup["team_id"], add_id)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200

    claim = await _get_claim(db_session_factory, claim_id)
    assert claim.status == TransactionStatus.APPROVED
    assert claim.reviewed_by == setup["commissioner_id"]


@pytest.mark.asyncio
async def test_manual_process_unaffected_when_best_ball_disabled(client, db_session_factory):
    """Regression pin: a league with no best_ball_settings at all
    processes exactly as before this phase."""
    setup = await _make_league(db_session_factory, best_ball_settings=None)
    league_id = setup["league_id"]
    add_id = await _make_free_agent(db_session_factory)
    claim_id = await _make_claim(db_session_factory, league_id, setup["team_id"], add_id)

    client.headers["Authorization"] = f"Bearer {setup['token']}"
    r = await client.post(f"/leagues/{league_id}/waivers/process")
    assert r.status_code == 200

    claim = await _get_claim(db_session_factory, claim_id)
    assert claim.status == TransactionStatus.APPROVED
