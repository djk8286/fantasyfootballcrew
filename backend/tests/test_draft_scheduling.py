"""
Tests for draft scheduling: POST/DELETE /drafts/{id}/schedule, the "it's
live" email on both manual start and scheduler auto-start, and
scheduler.py's _process_scheduled_drafts_once (auto-start + reminder).

Every notify_* in draft_notification_service opens its OWN session (see
that module's docstring re: the 2026-09-09 connection-pool-exhaustion
incident this replaced) and is fired via fire_and_forget_notify --
asyncio.create_task, not awaited inline. Two consequences for these
tests: (1) draft_notification_service's own `async_session` reference
needs patching to this test's isolated DB too, separately from
scheduler.py's (each `from ... import async_session` binds its own
module-level name -- patching one doesn't patch the other), and (2) a
test has to explicitly wait for whatever background task got created
before checking EmailSendLog, since the triggering endpoint/scheduler
call returns before that task necessarily finishes.

email_service._send stubs (no RESEND_API_KEY in test env) and logs to
EmailSendLog either way -- these tests check that table rather than
mocking Resend, same as test_email_send_log.py.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.models.user import User
from app.models.league import League, DraftStatus
from app.models.team import Team
from app.models.draft import Draft, DraftRunStatus
from app.models.email_send_log import EmailSendLog
from app.services.auth_service import create_access_token
from app.services.draft_manager import create_draft
import app.services.scheduler as scheduler_module
import app.services.draft_notification_service as notify_module
from app.services.scheduler import _process_scheduled_drafts_once


@pytest.fixture(autouse=True)
def _patch_notification_session(monkeypatch, db_session_factory):
    """Every test in this file needs this -- background notify tasks
    (fired from both the API endpoints and the scheduler) open their own
    session via draft_notification_service's async_session, which
    otherwise points at the real configured DATABASE_URL rather than
    this test's isolated in-memory DB."""
    monkeypatch.setattr(notify_module, "async_session", db_session_factory)


async def _wait_for_background_notifies() -> None:
    """Background notify tasks are created (via asyncio.create_task)
    synchronously inside the triggering call, so they already exist in
    _background_tasks by the time that call returns -- gathering
    whatever's still in there (already-finished tasks won't even be in
    the set anymore, having removed themselves via their done-callback)
    reliably waits out anything still in flight."""
    pending = list(notify_module._background_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _run_scheduled_drafts_pass(monkeypatch, db_session_factory) -> None:
    """_process_scheduled_drafts_once uses app.core.database.async_session
    directly (it's a standalone background-loop function, not a FastAPI
    request handler with an overridable get_db dependency) -- the
    `client`/db_session_factory fixtures only override the latter, so
    without this the scheduler would see the real configured DATABASE_URL
    instead of this test's isolated in-memory DB. Patched per-call rather
    than module-wide so it can't leak into other tests."""
    monkeypatch.setattr(scheduler_module, "async_session", db_session_factory)
    await _process_scheduled_drafts_once()
    await _wait_for_background_notifies()


async def _make_user(db_session_factory):
    async with db_session_factory() as db:
        user = User(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.local",
                    username=f"user{uuid.uuid4().hex[:8]}", hashed_password="x")
        db.add(user)
        await db.commit()
        token = create_access_token({"sub": user.id, "email": user.email})
        return user, token


async def _make_league_with_teams(db_session_factory, commissioner_id, owner_ids):
    async with db_session_factory() as db:
        league = League(id=str(uuid.uuid4()), name="Schedule Test League", commissioner_id=commissioner_id,
                         scoring_config={}, roster_slots={})
        db.add(league)
        await db.flush()
        for owner_id in owner_ids:
            db.add(Team(id=str(uuid.uuid4()), name=f"Team {owner_id[:6]}", league_id=league.id,
                        owner_id=owner_id, is_cpu=False, roster=[]))
        await db.commit()
        return league.id


async def _create_pending_draft(db_session_factory, league_id) -> str:
    async with db_session_factory() as db:
        draft = await create_draft(db, league_id)
        return draft.id


async def _email_logs(db_session_factory, email_type: str) -> list[EmailSendLog]:
    async with db_session_factory() as db:
        result = await db.execute(select(EmailSendLog).where(EmailSendLog.email_type == email_type))
        return list(result.scalars().all())


# ─── POST /drafts/{id}/schedule ──────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_draft_requires_commissioner(client, db_session_factory):
    commissioner, _ = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    _outsider, outsider_token = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    draft_id = await _create_pending_draft(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {outsider_token}"
    scheduled_for = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = await client.post(f"/drafts/{draft_id}/schedule", json={"scheduled_for": scheduled_for})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_schedule_draft_sets_time_and_emails_participants(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    draft_id = await _create_pending_draft(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    scheduled_for = datetime.now(timezone.utc) + timedelta(days=1)
    r = await client.post(f"/drafts/{draft_id}/schedule", json={"scheduled_for": scheduled_for.isoformat()})
    assert r.status_code == 200
    assert r.json()["scheduled_for"] is not None
    await _wait_for_background_notifies()

    async with db_session_factory() as db:
        draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()
        assert draft.scheduled_for is not None

    logs = await _email_logs(db_session_factory, "draft_scheduled")
    emailed = {l.to_email for l in logs}
    assert commissioner.email in emailed
    assert owner.email in emailed


@pytest.mark.asyncio
async def test_schedule_draft_rejects_already_started(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    draft_id = await _create_pending_draft(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    await client.post(f"/drafts/{draft_id}/start")

    scheduled_for = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = await client.post(f"/drafts/{draft_id}/schedule", json={"scheduled_for": scheduled_for})
    assert r.status_code == 400
    await _wait_for_background_notifies()


@pytest.mark.asyncio
async def test_cancel_draft_schedule_clears_time(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    draft_id = await _create_pending_draft(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    scheduled_for = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    await client.post(f"/drafts/{draft_id}/schedule", json={"scheduled_for": scheduled_for})
    await _wait_for_background_notifies()

    r = await client.delete(f"/drafts/{draft_id}/schedule")
    assert r.status_code == 200
    assert r.json()["scheduled_for"] is None


# ─── "it's live" email on manual start ───────────────────────────────

@pytest.mark.asyncio
async def test_manual_start_sends_live_email(client, db_session_factory):
    commissioner, commissioner_token = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    draft_id = await _create_pending_draft(db_session_factory, league_id)

    client.headers["Authorization"] = f"Bearer {commissioner_token}"
    r = await client.post(f"/drafts/{draft_id}/start")
    assert r.status_code == 200
    await _wait_for_background_notifies()

    logs = await _email_logs(db_session_factory, "draft_live")
    emailed = {l.to_email for l in logs}
    assert commissioner.email in emailed
    assert owner.email in emailed


# ─── scheduler._process_scheduled_drafts_once ────────────────────────

@pytest.mark.asyncio
async def test_scheduler_auto_starts_a_due_draft_and_notifies(db_session_factory, monkeypatch):
    commissioner, _ = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    draft_id = await _create_pending_draft(db_session_factory, league_id)

    async with db_session_factory() as db:
        draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()
        draft.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)  # already due
        await db.commit()

    await _run_scheduled_drafts_pass(monkeypatch, db_session_factory)

    async with db_session_factory() as db:
        draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()
        assert draft.status == DraftRunStatus.IN_PROGRESS

        league = (await db.execute(select(League).where(League.id == league_id))).scalar_one()
        assert league.draft_status == DraftStatus.IN_PROGRESS

    logs = await _email_logs(db_session_factory, "draft_live")
    assert {l.to_email for l in logs} >= {commissioner.email, owner.email}


@pytest.mark.asyncio
async def test_scheduler_sends_reminder_within_lead_window_once(db_session_factory, monkeypatch):
    commissioner, _ = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    draft_id = await _create_pending_draft(db_session_factory, league_id)

    async with db_session_factory() as db:
        draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()
        draft.scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=30)  # inside the 60-min lead window
        await db.commit()

    await _run_scheduled_drafts_pass(monkeypatch, db_session_factory)

    logs = await _email_logs(db_session_factory, "draft_reminder")
    assert {l.to_email for l in logs} >= {commissioner.email, owner.email}

    async with db_session_factory() as db:
        draft = (await db.execute(select(Draft).where(Draft.id == draft_id))).scalar_one()
        assert draft.reminder_email_sent_at is not None
        assert draft.status == DraftRunStatus.PENDING  # not started yet -- still 30 min out

    # Second tick shouldn't resend -- reminder_email_sent_at is already set.
    await _run_scheduled_drafts_pass(monkeypatch, db_session_factory)
    logs_after = await _email_logs(db_session_factory, "draft_reminder")
    assert len(logs_after) == len(logs)


@pytest.mark.asyncio
async def test_scheduler_ignores_drafts_without_a_schedule(db_session_factory, monkeypatch):
    commissioner, _ = await _make_user(db_session_factory)
    owner, _ = await _make_user(db_session_factory)
    league_id = await _make_league_with_teams(db_session_factory, commissioner.id, [commissioner.id, owner.id])
    await _create_pending_draft(db_session_factory, league_id)

    await _run_scheduled_drafts_pass(monkeypatch, db_session_factory)  # must not raise, must not touch anything

    logs = await _email_logs(db_session_factory, "draft_live")
    assert commissioner.email not in {l.to_email for l in logs}
