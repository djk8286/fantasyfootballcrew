"""
Tests for account deletion -- both the self-service DELETE /users/me
and the admin-triggered DELETE /admin/users/{id}, which now share the
exact same cleanup (account_deletion_service.delete_user_account,
extracted 2026-09-22). No test previously existed for DELETE /users/me
at all; this closes that gap while also proving the extraction didn't
change behavior.
"""
import uuid
import pytest
from sqlalchemy import select
from app.core.limiter import limiter
from app.models.user import User
from app.models.league import League, LeagueType
from app.models.team import Team
from app.models.league_join_request import LeagueJoinRequest
from app.models.notification import Notification, NotificationType
from app.services.auth_service import hash_password, create_access_token

PASSWORD = "realpassword123"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """DELETE /users/me is limited to 5/hour -- this file alone makes
    more than 5 calls to it across its tests. slowapi's Limiter is a
    process-wide in-memory singleton (see test_rate_limits.py's own
    docstring), so without this, later tests here would 429 on usage
    left behind by earlier ones."""
    limiter.reset()
    yield
    limiter.reset()


async def _make_user(db_session_factory, password: str | None = PASSWORD):
    async with db_session_factory() as db:
        user = User(
            id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
            username=f"user{uuid.uuid4().hex[:8]}",
            hashed_password=hash_password(password) if password else None,
        )
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email, "token_version": 0})
        return user, token


@pytest.mark.asyncio
async def test_delete_me_requires_correct_password_for_password_accounts(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={"password": "wrong-password"})
    assert r.status_code == 400

    async with db_session_factory() as db:
        assert (await db.execute(select(User).where(User.id == user.id))).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_delete_me_succeeds_with_correct_password(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={"password": PASSWORD})
    assert r.status_code == 200

    async with db_session_factory() as db:
        assert (await db.execute(select(User).where(User.id == user.id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_me_google_account_needs_no_password(client, db_session_factory):
    user, token = await _make_user(db_session_factory, password=None)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.request("DELETE", "/users/me", json={})
    assert r.status_code == 200

    async with db_session_factory() as db:
        assert (await db.execute(select(User).where(User.id == user.id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_me_blocked_as_sole_commissioner(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Sole Commish League", commissioner_id=user.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        db.add(Team(id=str(uuid.uuid4()), name="CPU Team", league_id=league.id, is_cpu=True, roster=[]))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.request("DELETE", "/users/me", json={"password": PASSWORD})
    assert r.status_code == 409

    async with db_session_factory() as db:
        assert (await db.execute(select(User).where(User.id == user.id))).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_delete_me_transfers_commissioner_role_to_a_real_successor(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    successor, _ = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Transfer League", commissioner_id=user.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        db.add(Team(id=str(uuid.uuid4()), name="Mine", league_id=league.id, owner_id=user.id, roster=[]))
        db.add(Team(id=str(uuid.uuid4()), name="Theirs", league_id=league.id, owner_id=successor.id, roster=[]))
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.request("DELETE", "/users/me", json={"password": PASSWORD})
    assert r.status_code == 200

    async with db_session_factory() as db:
        league_row = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        assert league_row.commissioner_id == successor.id
        # The now-ownerless team flips to CPU.
        mine = (await db.execute(select(Team).where(Team.name == "Mine"))).scalar_one()
        assert mine.owner_id is None
        assert mine.is_cpu is True


@pytest.mark.asyncio
async def test_delete_me_nulls_and_removes_other_owned_data(client, db_session_factory):
    user, token = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        db.add(Notification(id=str(uuid.uuid4()), user_id=user.id, type=NotificationType.MATCHUP_WON,
                             message="you won"))
        other_league_commissioner, _ = await _make_user(db_session_factory)
        db.add(other_league_commissioner)
        league = League(id=str(uuid.uuid4()), name="Someone Else's League",
                         commissioner_id=other_league_commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        db.add(LeagueJoinRequest(id=str(uuid.uuid4()), league_id=league.id, requested_by_user_id=user.id))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.request("DELETE", "/users/me", json={"password": PASSWORD})
    assert r.status_code == 200

    async with db_session_factory() as db:
        # This account's own notifications/join requests are hard-deleted.
        assert (await db.execute(select(Notification).where(Notification.user_id == user.id))).scalar_one_or_none() is None
        assert (await db.execute(
            select(LeagueJoinRequest).where(LeagueJoinRequest.requested_by_user_id == user.id)
        )).scalar_one_or_none() is None
