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
engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=300)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
