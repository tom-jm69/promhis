from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from promhis.config import settings

# asyncpg binds a connection to the event loop that created it; a pooled
# connection reused from a different loop raises confusing RuntimeErrors
# ("attached to a different loop"). This app only ever runs one event loop
# in production (a single uvicorn worker), so this can't happen there — but
# NullPool (a fresh connection per checkout, closed after use) is the
# simplest thing that's correct everywhere, and this is a low-volume webhook
# receiver where the extra per-request connect cost is negligible.
engine: AsyncEngine = create_async_engine(settings.database_url, poolclass=NullPool)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
