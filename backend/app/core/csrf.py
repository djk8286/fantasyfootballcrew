"""CSRF protection for cookie-authenticated requests.

Defense in depth on top of SameSite=Lax cookies: any state-changing
request (not GET/HEAD/OPTIONS) that carries one of our auth cookies must
come from an allowed Origin (falling back to the Referer's origin).
``Origin: null`` (sandboxed/opaque contexts) is refused. A request with
neither header is allowed: every current browser sends Origin on
cross-site POST/PUT/PATCH/DELETE (a page can't suppress it), so a
header-less request is a non-browser client, which holds no victim's
ambient cookies to abuse. Bearer-only requests carry no ambient
credentials and are not subject to CSRF, so they pass untouched.
"""
import json
from urllib.parse import urlsplit

from app.core.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUTH_COOKIES = ("ffc_access=", "ffc_refresh=")


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def allowed_origins() -> set[str]:
    raw = [*settings.CORS_ORIGINS, settings.FRONTEND_URL, *settings.CSRF_TRUSTED_ORIGINS]
    return {o for o in (_origin_of(u.strip()) for u in raw if u) if o}


class CSRFOriginMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        cookie = headers.get("cookie", "")
        # A request with an Authorization header is authenticated by that
        # header (deps prefer it over the cookie), and a cross-site page
        # can't attach one without passing our CORS preflight -- so only
        # cookie-only mutations need the Origin check.
        if headers.get("authorization") or not any(c in cookie for c in AUTH_COOKIES):
            return await self.app(scope, receive, send)
        raw_origin = headers.get("origin")
        referer = headers.get("referer")
        if raw_origin is None and not referer:
            return await self.app(scope, receive, send)
        if raw_origin is not None:
            origin = None if raw_origin == "null" else _origin_of(raw_origin)
        else:
            origin = _origin_of(referer)
        if origin is not None and origin in allowed_origins():
            return await self.app(scope, receive, send)
        body = json.dumps({"detail": "Cross-site request blocked"}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
