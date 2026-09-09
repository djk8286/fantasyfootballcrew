from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from app.core.config import settings

# pool_pre_ping: Railway idles/kills Postgres connections; without this,
# the first query on a connection that's gone stale since it was last
# used just errors instead of SQLAlchemy transparently reconnecting.
# pool_recycle: proactively retire connections before they get that old
# in the first place, rather than relying on pre_ping to catch every
# case.
#
# pool_size/max_overflow raised from SQLAlchemy's defaults (5+10=15) to
# 20+20=40 after the 2026-09-09 incident: a live draft's real concurrent
# load (every connected client polling /drafts/{id}/state every 2s, the
# league page every 8s, notifications, etc.) turned out to genuinely
# need more than 15 connections in flight at once even with that
# incident's actual bug (draft-notification emails holding one
# connection for way too long) separately fixed -- after that fix
# landed, the pool was STILL intermittently exhausting under real
# concurrent draft traffic. 40 is comfortably under Postgres's default
# max_connections (100) for a database this size with no other real
# consumers.
engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True, pool_recycle=300, pool_size=20, max_overflow=20)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
