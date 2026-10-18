"""
Tests for the admin dashboard (app/api/v1/admin.py) -- gated entirely
on User.is_admin, not on being a specific hardcoded account. Mostly
read-only; the league-detail drill-down and delete_league/
delete_user endpoints (2026-09-22) are the deliberate exceptions -- see
the module's own docstring for why deletion belongs here now.
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, LeagueType, DraftStatus
from app.models.team import Team
from app.models.draft import Draft, DraftPick, DraftRunStatus
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
async def test_non_admin_gets_403_on_league_detail_and_deletes(client, db_session_factory):
    _user, token = await _make_user(db_session_factory, is_admin=False)
    commissioner, _ = await _make_user(db_session_factory)
    other, _ = await _make_user(db_session_factory)
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Gated League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    assert (await client.get(f"/admin/leagues/{league_id}")).status_code == 403
    assert (await client.delete(f"/admin/leagues/{league_id}")).status_code == 403
    assert (await client.delete(f"/admin/users/{other.id}")).status_code == 403


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
    usernames = {u["username"] for u in r.json()["items"]}
    assert admin.username in usernames
    assert other.username in usernames
    # Email IS included here -- this is the admin-only view, distinct
    # from GET /users/{id}'s public (no-email) UserPublic response.
    admin_row = next(u for u in r.json()["items"] if u["id"] == admin.id)
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
        # 2026-09-09: the personal-tools endpoints (lineup/trade/bet) --
        # bet deliberately has no league_id (freeform, not league-scoped)
        # but DOES have a user_id, which is what by_user surfaces.
        db.add(AIUsageEvent(league_id=league.id, endpoint="lineup", user_id=commissioner.id))
        db.add(AIUsageEvent(endpoint="bet", user_id=commissioner.id))
        await db.commit()
        league_id = league.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/ai-usage")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 5
    assert data["last_24h"] >= 5
    endpoint_counts = {row["endpoint"]: row["count"] for row in data["by_endpoint"]}
    assert endpoint_counts["digest_generate"] >= 2
    assert endpoint_counts["chat"] >= 1
    assert endpoint_counts["lineup"] >= 1
    assert endpoint_counts["bet"] >= 1
    league_row = next(row for row in data["by_league"] if row["league_id"] == league_id)
    assert league_row["league_name"] == "AI Usage Test League"
    assert league_row["count"] == 4  # the league-less "bet" row is excluded
    user_row = next(row for row in data["by_user"] if row["user_id"] == commissioner.id)
    assert user_row["username"] == commissioner.username
    assert user_row["count"] == 2  # lineup + bet, the two rows with a user_id


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


# ─── /admin/leagues/{id} (detail drill-down) ──────────────────────────

@pytest.mark.asyncio
async def test_league_detail_shows_teams_drafts_and_scoring(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(
            id=str(uuid.uuid4()), name="Detail View League", commissioner_id=commissioner.id,
            league_type=LeagueType.STANDARD, scoring_config={"passing": {"pass_yd": 0.04}},
            roster_slots={"QB": 1},
        )
        db.add(league)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Real Team", league_id=league.id,
                     owner_id=owner.id, roster=[str(uuid.uuid4()), str(uuid.uuid4())], wins=3, losses=1)
        db.add(team)
        await db.flush()
        draft = Draft(id=str(uuid.uuid4()), league_id=league.id, status=DraftRunStatus.IN_PROGRESS,
                       current_round=2, total_rounds=15)
        db.add(draft)
        await db.flush()
        db.add(DraftPick(id=str(uuid.uuid4()), draft_id=draft.id, league_id=league.id,
                          team_id=team.id, player_id=str(uuid.uuid4()), round=1, pick_number=1))
        await db.commit()
        league_id, team_id, draft_id = league.id, team.id, draft.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get(f"/admin/leagues/{league_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["commissioner_username"] == commissioner.username
    assert body["scoring_config"] == {"passing": {"pass_yd": 0.04}}
    assert body["roster_slots"] == {"QB": 1}

    team_row = next(t for t in body["teams"] if t["id"] == team_id)
    assert team_row["owner_username"] == owner.username
    assert team_row["roster_size"] == 2
    assert team_row["wins"] == 3

    draft_row = next(d for d in body["drafts"] if d["id"] == draft_id)
    assert draft_row["status"] == "in_progress"
    assert draft_row["picks_made"] == 1
    assert draft_row["current_round"] == 2


@pytest.mark.asyncio
async def test_league_detail_404s_for_unknown_league(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.get("/admin/leagues/does-not-exist")
    assert r.status_code == 404


# ─── DELETE /admin/leagues/{id} ────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_delete_league_removes_it_and_its_teams(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    commissioner, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Dead League", commissioner_id=commissioner.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        team = Team(id=str(uuid.uuid4()), name="Dead Team", league_id=league.id, is_cpu=True, roster=[])
        db.add(team)
        await db.commit()
        league_id, team_id = league.id, team.id

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.delete(f"/admin/leagues/{league_id}")
    assert r.status_code == 200

    async with db_session_factory() as db:
        assert (await db.execute(select(League).where(League.id == league_id))).scalar_one_or_none() is None
        assert (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none() is None
        # The commissioner account itself is untouched by deleting their league.
        assert (await db.execute(select(User).where(User.id == commissioner.id))).scalar_one_or_none() is not None

    assert (await client.get(f"/admin/leagues/{league_id}")).status_code == 404


@pytest.mark.asyncio
async def test_admin_delete_league_404s_for_unknown_league(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.delete("/admin/leagues/does-not-exist")
    assert r.status_code == 404


# ─── DELETE /admin/users/{id} ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_delete_user_removes_the_account(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    target, _ = await _make_user(db_session_factory)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.delete(f"/admin/users/{target.id}")
    assert r.status_code == 200

    async with db_session_factory() as db:
        assert (await db.execute(select(User).where(User.id == target.id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_admin_delete_user_404s_for_unknown_user(client, db_session_factory):
    _admin, token = await _make_user(db_session_factory, is_admin=True)
    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.delete("/admin/users/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_delete_their_own_account_via_this_endpoint(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    client.headers["Authorization"] = f"Bearer {token}"

    r = await client.delete(f"/admin/users/{admin.id}")
    assert r.status_code == 400

    async with db_session_factory() as db:
        assert (await db.execute(select(User).where(User.id == admin.id))).scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_admin_delete_user_409s_when_sole_commissioner_of_a_league(client, db_session_factory):
    admin, token = await _make_user(db_session_factory, is_admin=True)
    target, _ = await _make_user(db_session_factory)

    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Solely Commissioned League", commissioner_id=target.id,
                         league_type=LeagueType.STANDARD, scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        # Only a CPU team -- no real successor exists.
        db.add(Team(id=str(uuid.uuid4()), name="CPU Team", league_id=league.id, is_cpu=True, roster=[]))
        await db.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    r = await client.delete(f"/admin/users/{target.id}")
    assert r.status_code == 409

    async with db_session_factory() as db:
        # Blocked -- the account must still exist.
        assert (await db.execute(select(User).where(User.id == target.id))).scalar_one_or_none() is not None
