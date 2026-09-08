"""
Tests for the read-only admin dashboard (app/api/v1/admin.py) -- gated
entirely on User.is_admin, not on being a specific hardcoded account.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from app.models.user import User
from app.models.league import League, DraftStatus
from app.models.team import Team
from app.models.draft import DraftPick
from app.models.ai_usage_event import AIUsageEvent
from app.models.email_send_log import EmailSendLog
from app.services.auth_service import hash_password, create_access_token


async def _make_user(db_session_factory, is_admin: bool = False):
    async with db_session_factory() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=f"{uuid.uuid4()}@test.local",
            username=f"user{uuid.uuid4().hex[:8]}",
            hashed_password=hash_password("realpassword123"),
            is_admin=is_admin,
        )
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email, "token_version": 0})
        return user, token


@pytest.mark.asyncio
async def test_non_admin_gets_403_on_every_admin_route(client, db_session_factory):
    _user, token = await _make_user(db_session_factory, is_admin=False)
    client.headers["Authorization"] = f"Bearer {token}"

    for path in ["/admin/stats", "/admin/users", "/admin/leagues"]:
        r = await client.get(path)
        assert r.status_code == 403, path


@pytest.mark.asyncio
async def test_logged_out_gets_401_on_admin_routes(client):
    client.headers.pop("Authorization", None)
    r = await client.get("/admin/stats")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_can_see_stats_and_users(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    other, _ = await _make_user(db_session_factory, is_admin=False)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.get("/admin/stats")
    assert r.status_code == 200
    assert r.json()["users"] >= 2

    r = await client.get("/admin/users")
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()}
    assert admin.username in usernames
    assert other.username in usernames
    # Email IS included here -- this is the admin-only view, distinct
    # from GET /users/{id}'s public (no-email) UserPublic response.
    admin_row = next(u for u in r.json() if u["id"] == admin.id)
    assert admin_row["email"] == admin.email
    assert admin_row["is_admin"] is True


@pytest.mark.asyncio
async def test_admin_leagues_list_includes_commissioner_and_team_count(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(
            id=str(uuid.uuid4()), name="Admin View Test League", commissioner_id=commissioner.id,
            scoring_config={}, roster_slots={},
        )
        db.add(league)
        await db.flush()
        db.add(Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id, is_cpu=True, roster=[]))
        db.add(Team(id=str(uuid.uuid4()), name="Team B", league_id=league.id, is_cpu=True, roster=[]))
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/leagues")
    assert r.status_code == 200
    row = next(l for l in r.json() if l["id"] == league_id)
    assert row["commissioner_username"] == commissioner.username
    assert row["commissioner_email"] == commissioner.email
    assert row["team_count"] == 2


# ─── /admin/ai-usage ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_usage_totals_and_breakdowns(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="AI Usage Test League", commissioner_id=commissioner.id,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        db.add(AIUsageEvent(league_id=league.id, endpoint="digest_generate"))
        db.add(AIUsageEvent(league_id=league.id, endpoint="digest_generate"))
        db.add(AIUsageEvent(league_id=league.id, endpoint="chat"))
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/ai-usage")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 3
    assert data["last_24h"] >= 3
    endpoint_counts = {row["endpoint"]: row["count"] for row in data["by_endpoint"]}
    assert endpoint_counts["digest_generate"] >= 2
    assert endpoint_counts["chat"] >= 1
    league_row = next(row for row in data["by_league"] if row["league_id"] == league_id)
    assert league_row["league_name"] == "AI Usage Test League"
    assert league_row["count"] == 3


# ─── /admin/league-health ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_league_health_flags_empty_league(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Empty Shell League", commissioner_id=commissioner.id,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/league-health")
    assert r.status_code == 200
    row = next(l for l in r.json() if l["id"] == league_id)
    assert "no_teams" in row["flags"]


@pytest.mark.asyncio
async def test_league_health_flags_never_started_after_stale_window(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        old_league = League(
            id=str(uuid.uuid4()), name="Old Never-Started League", commissioner_id=commissioner.id,
            scoring_config={}, roster_slots={}, draft_status=DraftStatus.NOT_STARTED,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        recent_league = League(
            id=str(uuid.uuid4()), name="Recent Never-Started League", commissioner_id=commissioner.id,
            scoring_config={}, roster_slots={}, draft_status=DraftStatus.NOT_STARTED,
        )
        db.add(old_league)
        db.add(recent_league)
        await db.commit()
        old_id, recent_id = old_league.id, recent_league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/league-health")
    assert r.status_code == 200
    rows_by_id = {l["id"]: l for l in r.json()}
    assert "never_started" in rows_by_id[old_id]["flags"]
    # Recent league is also empty (no_teams), but must NOT be flagged
    # never_started -- it hasn't been sitting long enough yet.
    assert "never_started" not in rows_by_id.get(recent_id, {"flags": []})["flags"]


@pytest.mark.asyncio
async def test_league_health_flags_stuck_draft(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(
            id=str(uuid.uuid4()), name="Stuck Draft League", commissioner_id=commissioner.id,
            scoring_config={}, roster_slots={}, draft_status=DraftStatus.IN_PROGRESS,
        )
        db.add(league)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Team A", league_id=league.id, is_cpu=True, roster=[])
        db.add(team)
        await db.flush()
        db.add(DraftPick(
            draft_id=str(uuid.uuid4()), league_id=league.id, team_id=team.id, player_id=str(uuid.uuid4()),
            pick_number=1, round=1, drafted_at=datetime.now(timezone.utc) - timedelta(hours=72),
        ))
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/league-health")
    assert r.status_code == 200
    row = next(l for l in r.json() if l["id"] == league_id)
    assert "stuck_draft" in row["flags"]


@pytest.mark.asyncio
async def test_league_health_excludes_mock_leagues(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Practice Draft", commissioner_id=commissioner.id,
                         scoring_config={}, roster_slots={}, is_mock=True)
        db.add(league)
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/league-health")
    assert r.status_code == 200
    assert all(l["id"] != league_id for l in r.json())


# ─── /admin/email-log ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_log_returns_recent_and_filters_by_status(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)

    async with db_session_factory() as db:
        db.add(EmailSendLog(to_email="a@test.local", email_type="verification", subject="Verify", status="sent"))
        db.add(EmailSendLog(to_email="b@test.local", email_type="league_invite", subject="Invite", status="failed", error_detail="403 Forbidden"))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/email-log")
    assert r.status_code == 200
    emails = {row["to_email"] for row in r.json()}
    assert "a@test.local" in emails
    assert "b@test.local" in emails

    r = await client.get("/admin/email-log?status=failed")
    assert r.status_code == 200
    rows = r.json()
    assert all(row["status"] == "failed" for row in rows)
    assert any(row["to_email"] == "b@test.local" and row["error_detail"] == "403 Forbidden" for row in rows)
