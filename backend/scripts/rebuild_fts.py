"""Rebuild FTS index to match current products table."""

import asyncio
import logging
from sqlalchemy import text
from grimoire.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def rebuild_fts():
    """Clear and rebuild FTS index from current products."""
    async with engine.begin() as conn:
        # Clear FTS table
        logger.info("Clearing FTS table...")
        await conn.execute(text("DELETE FROM products_fts"))
        
        # Rebuild from products table
        logger.info("Rebuilding FTS index from products table...")
        await conn.execute(text("""
            INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type)
            SELECT 
                id, 
                COALESCE(title, ''), 
                COALESCE(file_name, ''), 
                COALESCE(publisher, ''), 
                COALESCE(game_system, ''), 
                COALESCE(product_type, '')
            FROM products
        """))
        
        # Verify
        result = await conn.execute(text("SELECT COUNT(*) FROM products_fts"))
        fts_count = result.scalar()
        
        result = await conn.execute(text("SELECT COUNT(*) FROM products"))
        products_count = result.scalar()
        
        logger.info(f"✓ Rebuilt FTS index: {fts_count} entries (products table has {products_count})")
        
        if fts_count != products_count:
            logger.warning(f"Mismatch: FTS has {fts_count} but products has {products_count}")
        else:
            logger.info("✓ FTS and products tables are in sync")


if __name__ == "__main__":
    asyncio.run(rebuild_fts())
