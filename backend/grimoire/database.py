"""Database connection and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from grimoire.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# SQLite connection settings for better concurrency
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Set SQLite pragmas for better concurrent access and performance."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
    cursor.execute("PRAGMA busy_timeout=30000")  # Wait up to 30 seconds if locked
    cursor.execute("PRAGMA synchronous=NORMAL")  # Balance between safety and speed
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache for better query performance
    cursor.execute("PRAGMA temp_store=MEMORY")  # Use memory for temporary tables
    cursor.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
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
    """Dependency that provides a database session.

    Route handlers are responsible for calling commit() explicitly.
    The session is rolled back on exception and always closed.
    """
    async with async_session_maker() as session:
        try:
            yield session
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


async def _ensure_fts_table(conn) -> None:
    """Create the FTS5 virtual table and sync triggers if they don't exist."""
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='products_fts'")
    )
    if result.fetchone() is not None:
        return

    await conn.execute(text("""
        CREATE VIRTUAL TABLE products_fts USING fts5(
            title, file_name, publisher, game_system, product_type, extracted_text
        )
    """))
    await conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS products_fts_insert AFTER INSERT ON products BEGIN
            INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type)
            VALUES (new.id, new.title, new.file_name, new.publisher, new.game_system, new.product_type);
        END
    """))
    await conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS products_fts_update AFTER UPDATE ON products BEGIN
            DELETE FROM products_fts WHERE rowid = old.id;
            INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type)
            VALUES (new.id, new.title, new.file_name, new.publisher, new.game_system, new.product_type);
        END
    """))
    await conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS products_fts_delete AFTER DELETE ON products BEGIN
            DELETE FROM products_fts WHERE rowid = old.id;
        END
    """))


async def init_db() -> None:
    """Initialize database tables and seed default data."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_fts_table(conn)

    # Seed default exclusion rules
    from grimoire.services.exclusion_service import seed_default_rules
    async with async_session_maker() as session:
        await seed_default_rules(session)
