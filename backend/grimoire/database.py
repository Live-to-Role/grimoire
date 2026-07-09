"""Database connection and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import event, select, text
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
    """Create the FTS5 virtual table and sync triggers if they don't exist.

    Also backfills any products missing from the index (e.g. products that
    existed before the FTS table was created).
    """
    created_new = False
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='products_fts'")
    )
    if result.fetchone() is None:
        created_new = True
        await conn.execute(text("""
            CREATE VIRTUAL TABLE products_fts USING fts5(
                title, file_name, publisher, game_system, product_type,
                description, extracted_text
            )
        """))
    else:
        # Check if description column exists in FTS table by trying a query
        try:
            await conn.execute(text(
                "SELECT description FROM products_fts LIMIT 0"
            ))
        except Exception:
            # Rebuild FTS table with description column
            await conn.execute(text("DROP TABLE IF EXISTS products_fts"))
            await conn.execute(text("""
                CREATE VIRTUAL TABLE products_fts USING fts5(
                    title, file_name, publisher, game_system, product_type,
                    description, extracted_text
                )
            """))
            # Drop old triggers so they get recreated with description
            await conn.execute(text("DROP TRIGGER IF EXISTS products_fts_insert"))
            await conn.execute(text("DROP TRIGGER IF EXISTS products_fts_update"))
            await conn.execute(text("DROP TRIGGER IF EXISTS products_fts_delete"))
            created_new = True

    await conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS products_fts_insert AFTER INSERT ON products BEGIN
            INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type, description)
            VALUES (new.id, new.title, new.file_name, new.publisher, new.game_system, new.product_type, new.description);
        END
    """))
    await conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS products_fts_update AFTER UPDATE ON products BEGIN
            DELETE FROM products_fts WHERE rowid = old.id;
            INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type, description)
            VALUES (new.id, new.title, new.file_name, new.publisher, new.game_system, new.product_type, new.description);
        END
    """))
    await conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS products_fts_delete AFTER DELETE ON products BEGIN
            DELETE FROM products_fts WHERE rowid = old.id;
        END
    """))

    # Backfill: insert any products not yet in the FTS index
    result = await conn.execute(text("""
        INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type, description)
        SELECT p.id, COALESCE(p.title, ''), COALESCE(p.file_name, ''),
               COALESCE(p.publisher, ''), COALESCE(p.game_system, ''),
               COALESCE(p.product_type, ''), COALESCE(p.description, '')
        FROM products p
        WHERE p.id NOT IN (SELECT rowid FROM products_fts)
    """))


async def _ensure_columns(conn) -> None:
    """Add columns that may be missing from older databases."""
    migrations = [
        ("tags", "is_builtin", "BOOLEAN DEFAULT 0"),
        ("products", "is_image_content", "BOOLEAN DEFAULT 0"),
        ("products", "images_extracted", "BOOLEAN DEFAULT 0"),
        ("products", "image_count", "INTEGER"),
        ("products", "text_unextractable", "BOOLEAN DEFAULT 0"),
        ("products", "extraction_error", "TEXT"),
        ("processing_queue", "config", "TEXT"),
        ("products", "normalized_stem", "TEXT"),
        ("products", "is_superseded", "BOOLEAN DEFAULT 0"),
        ("products", "superseded_by_id", "INTEGER REFERENCES products(id)"),
        ("product_embeddings", "page_start", "INTEGER"),
        ("product_embeddings", "page_end", "INTEGER"),
    ]
    for table, column, col_type in migrations:
        try:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        except Exception:
            pass  # Column already exists


async def _backfill_normalized_stems(session):
    """One-time backfill: compute normalized_stem for all products missing it."""
    from grimoire.models.product import Product
    from grimoire.services.revision_service import normalize_stem

    result = await session.execute(
        select(Product).where(Product.normalized_stem.is_(None))
    )
    products = result.scalars().all()
    for product in products:
        product.normalized_stem = normalize_stem(product.file_name)
    if products:
        await session.commit()


async def init_db() -> None:
    """Initialize database tables and seed default data."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_fts_table(conn)
        await _ensure_columns(conn)

    # Seed default exclusion rules
    from grimoire.services.exclusion_service import seed_default_rules
    async with async_session_maker() as session:
        await seed_default_rules(session)

    # Seed built-in tags
    from grimoire.services.tag_service import seed_builtin_tags
    async with async_session_maker() as session:
        await seed_builtin_tags(session)

    # Backfill normalized stems for revision detection
    async with async_session_maker() as session:
        await _backfill_normalized_stems(session)
