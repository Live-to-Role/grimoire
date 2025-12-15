"""Full-text search service - manages SQLite FTS5 indexing."""

import json
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product

logger = logging.getLogger(__name__)


async def update_search_vector(db: AsyncSession, product: Product) -> bool:
    """
    Update the FTS5 index for a product based on extracted text.
    
    Uses SQLite FTS5 virtual table for full-text search.
    
    Args:
        db: Database session
        product: Product to update
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get extracted text content
        extracted_text = ""
        if product.extracted_text_path:
            text_path = Path(product.extracted_text_path)
            if text_path.exists():
                try:
                    with open(text_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        extracted_text = data.get("markdown", "")[:50000]  # Limit to 50k chars for FTS5
                except Exception as e:
                    logger.warning(f"Failed to read extracted text for product {product.id}: {e}")
        
        # Update FTS5 index - delete old entry and insert new
        # FTS5 uses rowid to link to main table
        await db.execute(
            text("DELETE FROM products_fts WHERE rowid = :product_id"),
            {"product_id": product.id}
        )
        
        await db.execute(
            text("""
                INSERT INTO products_fts(rowid, title, file_name, publisher, game_system, product_type, extracted_text)
                VALUES (:product_id, :title, :file_name, :publisher, :game_system, :product_type, :extracted_text)
            """),
            {
                "product_id": product.id,
                "title": product.title or "",
                "file_name": product.file_name or "",
                "publisher": product.publisher or "",
                "game_system": product.game_system or "",
                "product_type": product.product_type or "",
                "extracted_text": extracted_text,
            }
        )
        
        product.deep_indexed = True
        await db.commit()
        
        logger.info(f"Updated FTS index for product {product.id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update FTS index for product {product.id}: {e}")
        return False


async def update_all_search_vectors(db: AsyncSession, batch_size: int = 100) -> dict:
    """
    Update search vectors for all products with extracted text.
    
    Args:
        db: Database session
        batch_size: Number of products to process per batch
        
    Returns:
        Dict with success/failed counts
    """
    from sqlalchemy import select
    
    # Find products with text extracted but not deep indexed
    query = select(Product).where(
        Product.text_extracted == True,
        Product.deep_indexed == False,
    ).limit(batch_size)
    
    result = await db.execute(query)
    products = list(result.scalars().all())
    
    success = 0
    failed = 0
    
    for product in products:
        if await update_search_vector(db, product):
            success += 1
        else:
            failed += 1
    
    return {
        "processed": len(products),
        "success": success,
        "failed": failed,
    }


async def search_fts(
    db: AsyncSession,
    query: str,
    game_system: str | None = None,
    product_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Perform full-text search using SQLite FTS5.
    
    Args:
        db: Database session
        query: Search query string
        game_system: Optional filter by game system
        product_type: Optional filter by product type
        limit: Maximum results
        
    Returns:
        List of matching products with relevance scores
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from grimoire.models import ProductTag
    
    terms = query.strip().split()
    if not terms:
        return []
    
    # FTS5 query format - quote terms and use OR for flexible matching
    # Use * suffix for prefix matching
    fts_query = " OR ".join(f'"{term}"*' for term in terms)
    
    # SQLite FTS5 search with BM25 ranking
    sql = text("""
        SELECT 
            fts.rowid as product_id,
            bm25(products_fts) as rank,
            snippet(products_fts, 5, '<mark>', '</mark>', '...', 32) as snippet
        FROM products_fts fts
        JOIN products p ON p.id = fts.rowid
        WHERE products_fts MATCH :query
        AND p.is_duplicate = 0
        AND p.is_missing = 0
        AND (:game_system IS NULL OR p.game_system = :game_system)
        AND (:product_type IS NULL OR p.product_type = :product_type)
        ORDER BY rank
        LIMIT :limit
    """)
    
    try:
        result = await db.execute(sql, {
            "query": fts_query,
            "game_system": game_system,
            "product_type": product_type,
            "limit": limit,
        })
        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"FTS5 search failed: {e}")
        return []
    
    if not rows:
        return []
    
    # Fetch full product data
    product_ids = [row[0] for row in rows]
    rank_map = {row[0]: (abs(row[1]), row[2] if len(row) > 2 else None) for row in rows}
    
    products_query = (
        select(Product)
        .where(Product.id.in_(product_ids))
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    )
    products_result = await db.execute(products_query)
    products = {p.id: p for p in products_result.scalars().all()}
    
    # Build results with ranking
    from grimoire.api.routes.products import product_to_response
    
    results = []
    for product_id in product_ids:
        product = products.get(product_id)
        if not product:
            continue
        
        rank, snippet = rank_map.get(product_id, (0, None))
        item = product_to_response(product).model_dump()
        item["relevance_score"] = float(rank)
        if snippet:
            item["snippet"] = snippet
        results.append(item)
    
    return results


async def check_fts_available(db: AsyncSession) -> bool:
    """Check if FTS5 table exists."""
    try:
        result = await db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='products_fts'")
        )
        return result.fetchone() is not None
    except Exception:
        return False
