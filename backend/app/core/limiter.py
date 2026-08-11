"""
Rate limiting.

In-memory (per-process) counters via slowapi -- fine for this app's
single-instance Railway deployment (see railway.json / Procfile: one
uvicorn process, no --workers). If this ever moves to multiple instances,
these counters would need a shared backend (e.g. Redis) to stay accurate
across them; until then, in-memory is simpler and has one less moving
part to depend on.

Keyed by client IP. Applied narrowly to auth endpoints (login/register)
where it matters most -- brute-force password guessing and mass account
creation -- rather than as a blanket global limit, since a generous
global limit needs real traffic data to tune without risking false
positives on legitimate use (shared/NAT'd IPs, a busy page firing several
requests at once).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
