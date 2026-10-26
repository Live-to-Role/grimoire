"""Session access for MCP tool handlers.

Tool handlers run inside the MCP session manager, not a FastAPI request, so
``Depends(get_db)`` is unavailable. They open their own session the way the
queue worker does. Tests swap the factory for one bound to their engine.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_factory: async_sessionmaker | None = None


def set_session_factory(factory: async_sessionmaker | None) -> None:
    """Override where handlers get sessions. ``None`` restores the app engine."""
    global _factory
    _factory = factory


@asynccontextmanager
async def open_session() -> AsyncIterator[AsyncSession]:
    factory = _factory
    if factory is None:
        from grimoire.database import async_session_maker

        factory = async_session_maker
    async with factory() as db:
        yield db
