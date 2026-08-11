import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.core.limiter import limiter
from app.services.scheduler import run_scheduler
from app.api.v1 import (
    auth_router, users_router, leagues_router,
    teams_router, players_router, scoring_router,
    ai_router, drafts_router, standings_router,
    commissioner_router, trades_router, waivers_router,
    coaches_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
