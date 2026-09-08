"""
Tests for EmailSendLog -- the persisted record of every outbound-email
attempt (see email_service.py's _send/_log_send). Exists because the
2026-09-08 incident (invite AND verification emails silently 403ing for
weeks) was only ever visible in `railway logs`; this is the same
information made queryable.
"""
import uuid
import pytest
from sqlalchemy import select
from app.core.config import settings
from app.models.user import User
from app.models.email_send_log import EmailSendLog
from app.services import email_service


async def _log_rows(db_session_factory, to_email: str):
    async with db_session_factory() as db:
        result = await db.execute(select(EmailSendLog).where(EmailSendLog.to_email == to_email))
        return result.scalars().all()


@pytest.mark.asyncio
async def test_send_with_no_resend_key_logs_stubbed(db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    to_email = f"{uuid.uuid4()}@test.local"

    async with db_session_factory() as db:
        await email_service._send(
            to_email, "Test Subject", "text body", "<p>html</p>", "Test", "https://example.com/link", db, "password_reset",
        )

    rows = await _log_rows(db_session_factory, to_email)
    assert len(rows) == 1
    assert rows[0].status == "stubbed"
    assert rows[0].email_type == "password_reset"
    assert rows[0].subject == "Test Subject"
    assert rows[0].error_detail is None


@pytest.mark.asyncio
async def test_send_success_logs_sent(db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "Test <test@example.com>")
    to_email = f"{uuid.uuid4()}@test.local"

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass

    async def fake_post(self, url, headers=None, json=None):
        return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with db_session_factory() as db:
        await email_service._send(
            to_email, "Test Subject", "text body", "<p>html</p>", "Test", "https://example.com/link", db, "verification",
        )

    rows = await _log_rows(db_session_factory, to_email)
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert rows[0].email_type == "verification"


@pytest.mark.asyncio
async def test_send_failure_logs_failed_with_error_detail(db_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "Test <test@example.com>")
    to_email = f"{uuid.uuid4()}@test.local"

    async def fake_post(self, url, headers=None, json=None):
        raise RuntimeError("simulated network failure")

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with db_session_factory() as db:
        await email_service._send(
            to_email, "Test Subject", "text body", "<p>html</p>", "Test", "https://example.com/link", db, "league_invite",
        )

    rows = await _log_rows(db_session_factory, to_email)
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].email_type == "league_invite"
    assert "simulated network failure" in rows[0].error_detail


@pytest.mark.asyncio
async def test_registering_writes_an_email_send_log_row(client, db_session_factory, monkeypatch):
    """End-to-end -- no monkeypatching send_verification_email itself,
    unlike test_email_verification.py's tests, so this actually exercises
    the real logging path (test env has no RESEND_API_KEY -> stubbed)."""
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    email = f"{uuid.uuid4()}@example.com"
    r = await client.post("/auth/register", json={
        "email": email, "username": f"user{uuid.uuid4().hex[:8]}", "password": "password123",
    })
    assert r.status_code == 200

    rows = await _log_rows(db_session_factory, email)
    assert len(rows) == 1
    assert rows[0].email_type == "verification"
    assert rows[0].status == "stubbed"
