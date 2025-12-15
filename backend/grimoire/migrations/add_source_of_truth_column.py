"""
Migration script to add is_source_of_truth column to watched_folders table.
Run this to enable source of truth folder feature for duplicate resolution.
"""

import asyncio
import logging
from sqlalchemy import text
from grimoire.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MIGRATIONS = [
    ("watched_folders", "is_source_of_truth", "ALTER TABLE watched_folders ADD COLUMN is_source_of_truth BOOLEAN DEFAULT 0"),
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
