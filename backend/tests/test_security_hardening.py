"""Security audit 2026-10: limiter keying, JWT config, legacy hash compare, email log redaction."""
import hashlib
import jwt
import pytest
from datetime import datetime, timezone
from starlette.requests import Request

from app.core.config import Settings, settings
from app.core.limiter import client_ip_key
from app.services import auth_service, email_service


def _req(headers: dict, client=("100.64.0.7", 1234)) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/", "client": client,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    })


def test_spoofed_leading_xff_entries_do_not_change_key():
    real = _req({"x-forwarded-for": "203.0.113.9"})
    spoofed = _req({"x-forwarded-for": "1.2.3.4, 5.6.7.8, 203.0.113.9"})
    assert client_ip_key(real) == client_ip_key(spoofed) == "203.0.113.9"


def test_trusted_internal_hops_are_skipped():
    assert client_ip_key(_req({"x-forwarded-for": "9.9.9.9, 203.0.113.9, 100.64.0.3"})) == "203.0.113.9"


def test_garbage_xff_falls_back_to_real_ip_then_peer():
    assert client_ip_key(_req({"x-forwarded-for": "evil", "x-real-ip": "198.51.100.4"})) == "198.51.100.4"
    assert client_ip_key(_req({}, client=("198.51.100.5", 1))) == "198.51.100.5"


def test_access_token_default_expiry_is_7_days():
    tok = auth_service.create_access_token({"sub": "u"})
    exp = jwt.decode(tok, settings.JWT_SECRET, algorithms=["HS256"])["exp"]
    days = (exp - datetime.now(timezone.utc).timestamp()) / 86400
    assert 6.9 < days <= 7.0


def test_production_rejects_missing_or_short_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(ENVIRONMENT="production", _env_file=None)
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(ENVIRONMENT="production", JWT_SECRET="short", _env_file=None)
    assert Settings(ENVIRONMENT="production", JWT_SECRET="x" * 32, _env_file=None)
    assert Settings(ENVIRONMENT="development", _env_file=None)


def test_legacy_sha256_hash_still_verifies():
    h = "salt:" + hashlib.sha256(b"saltpw123").hexdigest()
    assert auth_service.verify_password("pw123", h)
    assert not auth_service.verify_password("nope", h)


@pytest.mark.asyncio
async def test_production_email_stub_redacts_link(monkeypatch, capsys):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    async def _noop(*a, **k): return None
    monkeypatch.setattr(email_service, "_log_send", _noop)
    await email_service._send("a@b.com", "s", "t", "h", "Password reset", "https://x/reset?token=SECRET", None, "password_reset")
    out = capsys.readouterr().out
    assert "a@b.com" in out and "password_reset" in out and "SECRET" not in out
