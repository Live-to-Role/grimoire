"""
Migration script to add FTS and semantic search support for SQLite.
Run this to set up full-text search on existing database.

Usage:
    cd backend
    python -m grimoire.migrations.add_search_columns
"""

import asyncio
import logging
from sqlalchemy import text
from grimoire.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table (SQLite)."""
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    columns = [row[1] for row in result.fetchall()]
    return column in columns


async def table_exists(conn, table: str) -> bool:
    """Check if a table exists (SQLite)."""
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table}
    )
    return result.fetchone() is not None


async def run_migrations():
    """Run all pending migrations for SQLite."""
    async with engine.begin() as conn:
        # 1. Add deep_indexed column if not exists
        if not await column_exists(conn, "products", "deep_indexed"):
            logger.info("Adding products.deep_indexed column")
            await conn.execute(text(
                "ALTER TABLE products ADD COLUMN deep_indexed BOOLEAN DEFAULT 0"
            ))
            logger.info("✓ Added deep_indexed column")
        else:
            logger.info("✓ deep_indexed column already exists")
        
        # 2. Create FTS5 virtual table for full-text search
        # Drop and recreate if it exists with wrong schema
        if await table_exists(conn, "products_fts"):
            logger.info("Dropping existing products_fts table to recreate with correct schema")
            await conn.execute(text("DROP TABLE products_fts"))
        
        logger.info("Creating FTS5 virtual table")
        await conn.execute(text("""
            CREATE VIRTUAL TABLE products_fts USING fts5(
                title,
                file_name,
                publisher,
                game_system,
                product_type
            )
        """))
        logger.info("✓ Created products_fts table")
        
        # 3. Create triggers to keep FTS in sync
        # Insert trigger
        try:
            await conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS products_fts_insert AFTER INSERT ON products BEGIN
                    INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type)
                    VALUES (new.id, new.title, new.file_name, new.publisher, new.game_system, new.product_type);
                END
            """))
            logger.info("✓ Created insert trigger")
        except Exception as e:
            logger.info(f"Insert trigger may already exist: {e}")
        
        # Update trigger
        try:
            await conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS products_fts_update AFTER UPDATE ON products BEGIN
                    DELETE FROM products_fts WHERE rowid = old.id;
                    INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type)
                    VALUES (new.id, new.title, new.file_name, new.publisher, new.game_system, new.product_type);
                END
            """))
            logger.info("✓ Created update trigger")
        except Exception as e:
            logger.info(f"Update trigger may already exist: {e}")
        
        # Delete trigger  
        try:
            await conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS products_fts_delete AFTER DELETE ON products BEGIN
                    DELETE FROM products_fts WHERE rowid = old.id;
                END
            """))
            logger.info("✓ Created delete trigger")
        except Exception as e:
            logger.info(f"Delete trigger may already exist: {e}")
    
    logger.info("All migrations complete!")
    logger.info("")
    logger.info("To populate FTS index with existing data, run:")
    logger.info("  python -m grimoire.migrations.add_search_columns --rebuild-fts")


async def rebuild_fts_index():
    """Rebuild FTS index from existing products."""
    async with engine.begin() as conn:
        logger.info("Rebuilding FTS index...")
        
        # Clear existing FTS data
        try:
            await conn.execute(text("DELETE FROM products_fts"))
        except Exception as e:
            logger.warning(f"Could not clear FTS table, may need to run migrations first: {e}")
            return
        
        # Repopulate from products table
        await conn.execute(text("""
            INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type)
            SELECT id, COALESCE(title, ''), COALESCE(file_name, ''), 
                   COALESCE(publisher, ''), COALESCE(game_system, ''), COALESCE(product_type, '')
            FROM products
        """))
        
        result = await conn.execute(text("SELECT COUNT(*) FROM products_fts"))
        count = result.scalar()
        logger.info(f"✓ Indexed {count} products")


if __name__ == "__main__":
    import sys
    if "--rebuild-fts" in sys.argv:
        asyncio.run(rebuild_fts_index())
    else:
        asyncio.run(run_migrations())
