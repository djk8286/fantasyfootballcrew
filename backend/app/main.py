from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
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
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="Customizable Fantasy Football Platform",
    version="0.1.0",
    lifespan=lifespan,
)

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
