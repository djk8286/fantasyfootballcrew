"""
Shared fixtures for scoring engine tests, plus (below) a real async-DB +
HTTP test client setup for endpoint-level integration tests -- currently
just the trade/waiver concurrency tests, but reusable for anything that
needs one.
"""
import uuid
import pytest
import pytest_asyncio
from typing import Dict, Any
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Import the REAL default config rather than keeping a hand-duplicated copy
# here. A duplicate is exactly how this file went stale: scoring_engine's
# DEFAULT_SCORING keys were corrected to match Sleeper's actual API field
# names (see the comment above DEFAULT_SCORING in scoring_engine.py --
# pass_yds -> pass_yd, int -> pass_int, def_sack -> sack, etc.), but this
# file kept its own pre-rename copy, so every fixture below was silently
# testing against stat keys the real bonus/long-TD lookups (which use the
# real keys internally) could never match.
from app.services.scoring_engine import DEFAULT_SCORING


@pytest.fixture
def default_scoring() -> Dict[str, Any]:
    """Standard PPR scoring config (the app's real default, not a copy)."""
    return dict(DEFAULT_SCORING)


@pytest.fixture
def qb_stats() -> Dict[str, Any]:
    """Sample QB weekly stats: 300 yds, 3 TDs, 1 INT, 15 rush yds."""
    return {
        "pass_yd": 300,
        "pass_td": 3,
        "pass_int": 1,
        "pass_2pt": 0,
        "rush_yd": 15,
        "rush_td": 0,
    }


@pytest.fixture
def rb_stats() -> Dict[str, Any]:
    """Sample RB weekly stats: 100 rush yds, 1 TD, 4 rec, 30 rec yds."""
    return {
        "rush_yd": 100,
        "rush_td": 1,
        "rec": 4,
        "rec_yd": 30,
        "rec_td": 0,
    }


@pytest.fixture
def wr_stats() -> Dict[str, Any]:
    """Sample WR weekly stats: 8 rec, 120 yds, 1 TD."""
    return {
        "rec": 8,
        "rec_yd": 120,
        "rec_td": 1,
        "rush_yd": 0,
        "rush_td": 0,
    }


@pytest.fixture
def te_stats() -> Dict[str, Any]:
    """Sample TE weekly stats: 5 rec, 60 yds, 1 TD."""
    return {
        "rec": 5,
        "rec_yd": 60,
        "rec_td": 1,
    }


@pytest.fixture
def kicker_stats() -> Dict[str, Any]:
    """Sample K weekly stats: 2 FG (30-39), 1 FG (40-49), 3 XP."""
    return {
        "fgm_30_39": 2,
        "fgm_40_49": 1,
        "fgm_50_59": 0,
        "xpm": 3,
    }


@pytest.fixture
def defense_stats() -> Dict[str, Any]:
    """Sample DEF weekly stats: 3 sacks, 2 INTs, 1 fum rec, 1 TD, 45 return yds."""
    return {
        "sack": 3,
        "int": 2,
        "fum_rec": 1,
        "safe": 0,
        "def_td": 1,
        "st_fum_rec": 0,
        "st_td": 0,
        "kr_yd": 45,
    }


@pytest.fixture
def empty_stats() -> Dict[str, Any]:
    """Empty stats dict for edge case testing."""
    return {}


@pytest.fixture
def custom_rule_no_td_bonus() -> Dict[str, Any]:
    """A scoring config that disables the long TD bonus."""
    config = dict(DEFAULT_SCORING)
    config["bonus"] = {
        "pass_300_yds": 3,
        "rush_100_yds": 3,
        "rec_100_yds": 3,
    }
    return config


# ─── Async DB + HTTP integration test infrastructure ──────────────────
#
# A real in-memory SQLite DB per test (StaticPool + check_same_thread=False
# so every connection -- including the FastAPI app's, via the dependency
# override below -- shares the exact same in-memory database rather than
# each getting its own empty one, which is aiosqlite's default per-
# connection behavior). Genuinely exercises the app's real endpoints,
# real auth, real CAS logic -- not a reimplementation of it. SQLite's
# with_for_update() is a no-op (same as production's own comments already
# note), which is actually useful here: on SQLite, the roster_version
# compare-and-swap is the ONLY thing preventing a lost update, so a test
# that passes here is specifically confirming that check works, not
# incidentally passing because a real row lock papered over a gap in it.

from app.core.database import Base, get_db
from app.main import app as fastapi_app
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.player import Player
from app.services.auth_service import create_access_token


@pytest_asyncio.fixture
async def db_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session_factory):
    """An httpx.AsyncClient hitting the real FastAPI app in-process (ASGI
    transport, no real network/port), with get_db overridden to the
    isolated per-test SQLite DB above. Auth is NOT overridden -- tests
    create real users and pass real JWTs, so authorization logic is
    exercised for real too, not bypassed."""
    async def _get_test_db():
        async with db_session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = _get_test_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as ac:
        yield ac
    fastapi_app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def seed(db_session_factory):
    """Creates a commissioner (with a real bearer token) + a league + 3
    teams (a, b, c) + enough players to build rosters with, all directly
    via the DB (not through the API -- these tests are about the
    trade/waiver endpoints specifically, not league/team/draft setup).
    Returns a dict of everything a test typically needs."""
    async with db_session_factory() as db:
        commissioner = User(
            id=str(uuid.uuid4()), email="commish@test.local", username="commish",
            hashed_password="x",
        )
        db.add(commissioner)
        await db.flush()

        league = League(
            id=str(uuid.uuid4()), name="Concurrency Test League",
            commissioner_id=commissioner.id, league_type=LeagueType.STANDARD,
            draft_status=DraftStatus.COMPLETED, scoring_config={}, roster_slots={},
        )
        db.add(league)
        await db.flush()

        players = [
            Player(id=str(uuid.uuid4()), sleeper_id=f"sleeper-{i}", first_name=f"Player{i}",
                   last_name="Test", position="RB")
            for i in range(6)
        ]
        db.add_all(players)
        await db.flush()
        player_ids = [p.id for p in players]

        team_a = Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id,
                       owner_id=commissioner.id, roster=player_ids[0:2], roster_version=0)
        team_b = Team(id=str(uuid.uuid4()), name="Team B", league_id=league.id,
                       owner_id=commissioner.id, roster=player_ids[2:4], roster_version=0)
        team_c = Team(id=str(uuid.uuid4()), name="Team C", league_id=league.id,
                       owner_id=commissioner.id, roster=player_ids[4:6], roster_version=0)
        db.add_all([team_a, team_b, team_c])
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})

        return {
            "token": token,
            "commissioner_id": commissioner.id,
            "league_id": league.id,
            "team_a": team_a.id, "team_b": team_b.id, "team_c": team_c.id,
            "players": player_ids,  # [a0, a1, b0, b1, c0, c1]
            "db_session_factory": db_session_factory,
        }


@pytest_asyncio.fixture
async def guillotine_seed(db_session_factory):
    """4-team GUILLOTINE league (t1..t4), all empty rosters -- score is
    entirely controlled per-test via flat_weekly Coach bonuses (see
    test_guillotine_elimination.py's _add_coach helper). Not the shared
    3-team `seed` fixture above, since exercising "keeps eliminating
    while >2 remain, then locks the finale" needs at least 4 teams.
    Shared across every Phase 4 ("Guillotine + Custom Twist") test file."""
    async with db_session_factory() as db:
        commissioner = User(id=str(uuid.uuid4()), email="gcommish@test.local",
                             username="gcommish", hashed_password="x")
        db.add(commissioner)
        await db.flush()

        league = League(id=str(uuid.uuid4()), name="Guillotine Test League",
                         commissioner_id=commissioner.id, league_type=LeagueType.GUILLOTINE,
                         draft_status=DraftStatus.COMPLETED, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()

        teams = [
            Team(id=str(uuid.uuid4()), name=f"Team {i + 1}", league_id=league.id,
                 owner_id=commissioner.id, roster=[], roster_version=0)
            for i in range(4)
        ]
        db.add_all(teams)
        await db.commit()

        token = create_access_token({"sub": commissioner.id, "email": commissioner.email})

        return {
            "token": token,
            "commissioner_id": commissioner.id,
            "league_id": league.id,
            "team_ids": [t.id for t in teams],
            "db_session_factory": db_session_factory,
        }
