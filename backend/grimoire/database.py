"""Database connection and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from grimoire.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# SQLite connection settings for better concurrency
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Set SQLite pragmas for better concurrent access."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
    cursor.execute("PRAGMA busy_timeout=30000")  # Wait up to 30 seconds if locked
    cursor.execute("PRAGMA synchronous=NORMAL")  # Balance between safety and speed
    cursor.close()


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    pool_pre_ping=True,  # Check connections before use
)

# Register the pragma setter for SQLite connections
event.listen(engine.sync_engine, "connect", set_sqlite_pragma)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_db_session():
    """
    Context manager for database sessions outside of FastAPI requests.
    
    Usage:
        async with get_db_session() as session:
            # use session
    """
    return async_session_maker()


async def init_db() -> None:
    """Initialize database tables and seed default data."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Seed default exclusion rules
    from grimoire.services.exclusion_service import seed_default_rules
    async with async_session_maker() as session:
        await seed_default_rules(session)
