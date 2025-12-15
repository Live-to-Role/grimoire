"""
Migration script to add columns for large library support.
Run this to add duplicate detection and exclusion columns to existing database.
"""

import asyncio
import logging
from sqlalchemy import text
from grimoire.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MIGRATIONS = [
    # Duplicate detection columns
    ("products", "is_duplicate", "ALTER TABLE products ADD COLUMN is_duplicate BOOLEAN DEFAULT 0"),
    ("products", "duplicate_of_id", "ALTER TABLE products ADD COLUMN duplicate_of_id INTEGER REFERENCES products(id)"),
    ("products", "duplicate_reason", "ALTER TABLE products ADD COLUMN duplicate_reason VARCHAR(50)"),
    
    # Exclusion/missing status columns
    ("products", "is_excluded", "ALTER TABLE products ADD COLUMN is_excluded BOOLEAN DEFAULT 0"),
    ("products", "excluded_by_rule_id", "ALTER TABLE products ADD COLUMN excluded_by_rule_id INTEGER"),
    ("products", "exclusion_override", "ALTER TABLE products ADD COLUMN exclusion_override BOOLEAN DEFAULT 0"),
    ("products", "is_missing", "ALTER TABLE products ADD COLUMN is_missing BOOLEAN DEFAULT 0"),
    ("products", "missing_since", "ALTER TABLE products ADD COLUMN missing_since DATETIME"),
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
    
    logger.info("All migrations complete")


if __name__ == "__main__":
    asyncio.run(run_migrations())
