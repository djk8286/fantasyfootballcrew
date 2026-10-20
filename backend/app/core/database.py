from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from app.core.config import settings

# pool_pre_ping: Railway idles/kills Postgres connections; without this,
# the first query on a connection that's gone stale since it was last
# used just errors instead of SQLAlchemy transparently reconnecting.
# pool_recycle: proactively retire connections before they get that old
# in the first place, rather than relying on pre_ping to catch every
# case. Everything else (pool_size/max_overflow/timeout) is left at
# SQLAlchemy's own defaults -- they were never tuned at all before this,
# and 5+10 isn't oversized for Railway's connection caps; pre_ping/
# recycle were the real gap (Production Quality Hardening, Phase 3).
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# Pool sizing (2026-10-19): the 5+10 default ran dry when a burst of slow
# /drafts/{id}/state polls each held a connection, and the 30s pool
# timeout turned that into 30s hangs everywhere. The root fix is making
# /state cheap (draft_board.py); this adds headroom (Railway Postgres
# allows 100) and fails fast instead of hanging.
_pool_kwargs = {} if _is_sqlite else {"pool_size": 10, "max_overflow": 10, "pool_timeout": 10}

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=300, **_pool_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# A separate, small pool for the draft clock watchdog, so request load can
# never starve it of connections again (2026-10-19: "[draft_timer] Check
# iteration failed: QueuePool limit ... reached" -- CPU picks and expired
# clocks stalled for minutes). SQLite (dev/tests) just shares the engine.
background_engine = engine if _is_sqlite else create_async_engine(
    settings.DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=300,
    pool_size=2, max_overflow=2, pool_timeout=10,
)
background_session = async_sessionmaker(background_engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
