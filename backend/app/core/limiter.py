"""
Rate limiting.

In-memory (per-process) counters via slowapi -- fine for this app's
single-instance Railway deployment (one uvicorn process, no --workers).
If this ever moves to multiple instances, counters need a shared backend.

Keyed by client IP -- see client_ip_key() for how that IP is derived
without trusting client-controlled X-Forwarded-For entries.
"""
import hmac
import ipaddress
import logging

from slowapi import Limiter
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger(__name__)


def _trusted_networks():
    nets = []
    for raw in settings.TRUSTED_PROXY_CIDRS:
        try:
            nets.append(ipaddress.ip_network(raw.strip(), strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXY_CIDRS entry %r", raw)
    return nets


_TRUSTED = _trusted_networks()


def _is_trusted(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in _TRUSTED)


def _valid_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def client_ip_key(request: Request) -> str:
    """Rate-limit key: the real client IP, resistant to XFF spoofing.

    1. X-Real-IP -- Railway's edge sets this authoritatively to the
       connecting client's IP (Railway public-networking docs), so a
       client can't choose it as long as the edge is the only way in.
    2. Otherwise the rightmost X-Forwarded-For hop not in
       TRUSTED_PROXY_CIDRS (leftmost entries are client-controlled;
       proxies only append).
    3. Otherwise the raw socket peer.

    Reads raw headers deliberately, not request.client, because
    ProxyHeadersMiddleware rewrites request.client from the *leftmost*
    (spoofable) XFF entry.
    """
    # 0. Requests relayed by our own Next.js /api proxy on Vercel: Railway
    #    sees Vercel's egress IP (shared by every visitor), so the proxy
    #    forwards the visitor IP Vercel observed in X-FFC-Client-IP, and
    #    authenticates itself with a shared secret. Without the exact
    #    secret the header is ignored, so it can't be spoofed by callers
    #    hitting Railway directly.
    secret = settings.PROXY_SHARED_SECRET
    if secret:
        presented = request.headers.get("x-ffc-proxy-secret", "")
        if presented and hmac.compare_digest(presented.encode(), secret.encode()):
            proxied_ip = request.headers.get("x-ffc-client-ip", "").strip()
            if proxied_ip and _valid_ip(proxied_ip):
                return proxied_ip
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip and _valid_ip(real_ip):
        return real_ip
    xff = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    for host in reversed(hops):
        if _valid_ip(host) and not _is_trusted(host):
            return host
    scope_client = request.scope.get("client")
    return scope_client[0] if scope_client else "127.0.0.1"


limiter = Limiter(key_func=client_ip_key)
