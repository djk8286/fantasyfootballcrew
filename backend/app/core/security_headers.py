"""
Baseline security response headers, applied to every response.

Deliberately does NOT set Content-Security-Policy here. CSP protects the
document that's actually rendering in a browser -- for this app that's
the Next.js frontend (see frontend/next.config.ts, where a real CSP is
enforced), not this API. A CSP header on JSON responses consumed by
fetch() from another origin has no meaningful browser-enforced effect on
the caller, and applying one broadly here WOULD break this service's own
HTML surfaces -- Swagger UI at /docs and ReDoc at /redoc both load their
JS/CSS from a CDN (cdn.jsdelivr.net), so a strict default-src would
silently blank those pages. Not worth the complexity of special-casing
two routes for a header that isn't doing real protective work here.

The headers below ARE worth setting globally: none of them have a
plausible downside for an API service, unlike CSP.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # HSTS is a no-op (browsers ignore it) when delivered over plain
        # HTTP, so this is safe to send unconditionally -- it only takes
        # effect on the real https:// domain Railway terminates TLS for.
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # DENY, not SAMEORIGIN -- nothing on this API, including /docs,
        # is meant to be embedded in a frame anywhere, this origin included.
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response
