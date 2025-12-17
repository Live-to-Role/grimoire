"""
Migration script to add Codex-compatible fields to products table.
Run this to add description, marketplace links, series info, and other Codex fields.
"""

import asyncio
import logging
from sqlalchemy import text
from grimoire.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MIGRATIONS = [
    # Description
    ("products", "description", "ALTER TABLE products ADD COLUMN description TEXT"),
    
    # Classification - setting
    ("products", "setting", "ALTER TABLE products ADD COLUMN setting VARCHAR(255)"),
    
    # Series information
    ("products", "series", "ALTER TABLE products ADD COLUMN series VARCHAR(255)"),
    ("products", "series_order", "ALTER TABLE products ADD COLUMN series_order VARCHAR(50)"),
    
    # Publication details
    ("products", "format", "ALTER TABLE products ADD COLUMN format VARCHAR(20)"),
    ("products", "isbn", "ALTER TABLE products ADD COLUMN isbn VARCHAR(20)"),
    ("products", "msrp", "ALTER TABLE products ADD COLUMN msrp REAL"),
    
    # Marketplace links
    ("products", "dtrpg_url", "ALTER TABLE products ADD COLUMN dtrpg_url TEXT"),
    ("products", "itch_url", "ALTER TABLE products ADD COLUMN itch_url TEXT"),
    
    # JSON array fields for Codex compatibility
    ("products", "themes", "ALTER TABLE products ADD COLUMN themes TEXT"),
    ("products", "content_warnings", "ALTER TABLE products ADD COLUMN content_warnings TEXT"),
]


async def column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    columns = [row[1] for row in result.fetchall()]
    return column in columns


async def run_migrations():
    """Run all pending migrations."""
    async with engine.begin() as conn:
        for table, column, sql in MIGRATIONS:
            if await column_exists(conn, table, column):
                logger.info(f"Column {table}.{column} already exists, skipping")
                continue
            
            logger.info(f"Adding column {table}.{column}")
            try:
                await conn.execute(text(sql))
                logger.info(f"Successfully added {table}.{column}")
            except Exception as e:
                logger.error(f"Failed to add {table}.{column}: {e}")
                raise
    
    logger.info("All Codex field migrations complete")


if __name__ == "__main__":
    asyncio.run(run_migrations())
