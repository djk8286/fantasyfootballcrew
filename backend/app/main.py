import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import settings
from app.core.database import engine
from app.core.limiter import limiter
from app.core.sentry import init_sentry
from app.services.scheduler import run_scheduler
from app.api.v1 import (
    auth_router, users_router, leagues_router,
    teams_router, players_router, scoring_router,
    ai_router, drafts_router, standings_router,
    commissioner_router, trades_router, waivers_router,
    coaches_router, lineups_router, notifications_router,
)

# Before the FastAPI app is constructed, so instrumentation covers
# everything from the very first request. No-ops entirely without
# SENTRY_DSN set -- see app/core/sentry.py.
init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is Alembic's job now, not this process's -- `alembic upgrade
    # head` runs as part of the deploy itself (see railway.json's
    # startCommand), before this app even starts. This used to be
    # `Base.metadata.create_all` on every startup, which only ever created
    # missing tables and could never apply an ALTER to an existing one --
    # every real schema change still needed a separate hand-rolled
    # migrate_add_*.py run manually before the deploy that depended on it.
    # See DEPLOYMENT.md for the migration workflow this replaced.

    # Background player/stats sync -- see app/services/scheduler.py. Runs
    # for the lifetime of the process; replaces the manual "run this script
    # after every deploy" step documented in DEPLOYMENT.md.
    scheduler_task = asyncio.create_task(run_scheduler())

    yield

    # Shutdown
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="Customizable Fantasy Football Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting -- see app/core/limiter.py. Per-route limits (login/register)
# are applied in their own routers via @limiter.limit(...); this just wires
# the shared limiter into the app so those decorators work.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Railway (and every PaaS like it) puts the app behind a reverse proxy, so
# the raw ASGI connection's client is Railway's internal edge/proxy address
# -- not the visitor's. Confirmed in Railway's own logs: every request
# logged from a different 100.64.0.x address (RFC 6598 shared address
# space), never a real public IP. Without this, get_remote_address() (what
# the rate limiter keys on) reads that rotating proxy address instead of
# the actual caller, which would make login/register rate limiting nearly
# useless -- attempts would spread across whichever internal address
# happened to handle each one instead of accumulating against the abuser.
# Added last / outermost so it rewrites request.client from X-Forwarded-For
# before anything else (rate limiting included) reads it. trusted_hosts="*"
# because Railway's proxy is the only path to this process -- there's no
# direct public route where a client could spoof X-Forwarded-For itself.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Register routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(leagues_router, prefix="/api/v1")
app.include_router(teams_router, prefix="/api/v1")
app.include_router(players_router, prefix="/api/v1")
app.include_router(scoring_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(drafts_router, prefix="/api/v1")
app.include_router(standings_router, prefix="/api/v1")
app.include_router(commissioner_router, prefix="/api/v1")
app.include_router(trades_router, prefix="/api/v1")
app.include_router(waivers_router, prefix="/api/v1")
app.include_router(coaches_router, prefix="/api/v1")
app.include_router(lineups_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "app": settings.APP_NAME}
