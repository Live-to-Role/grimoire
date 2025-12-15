"""Search API endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from grimoire.api.deps import DbSession
from grimoire.models import Product, ProductTag

router = APIRouter()


def search_in_extracted_text(product: Product, query: str) -> list[dict] | None:
    """Search within a product's extracted text and return matching snippets."""
    if not product.text_extracted or not product.extracted_text_path:
        return None

    text_path = Path(product.extracted_text_path)
    if not text_path.exists():
        return None

    try:
        with open(text_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            markdown = data.get("markdown", "")
    except Exception:
        return None

    if not markdown:
        return None

    query_lower = query.lower()
    snippets = []

    lines = markdown.split('\n')
    for i, line in enumerate(lines):
        if query_lower in line.lower():
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            context = '\n'.join(lines[start:end]).strip()

            if len(context) > 300:
                idx = line.lower().find(query_lower)
                start_char = max(0, idx - 100)
                end_char = min(len(line), idx + len(query) + 100)
                context = "..." + line[start_char:end_char] + "..."

            snippets.append({
                "line": i + 1,
                "snippet": context,
            })

            if len(snippets) >= 3:
                break

    return snippets if snippets else None


@router.get("")
async def search_products(
    db: DbSession,
    q: str = Query(..., min_length=1, description="Search query"),
    game_system: str | None = Query(None, description="Filter by game system"),
    product_type: str | None = Query(None, description="Filter by product type"),
    search_content: bool = Query(False, description="Search within extracted text"),
    use_fts: bool = Query(True, description="Use PostgreSQL full-text search"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
) -> dict:
    """Full-text search across products.
    
    When use_fts=True (default), uses PostgreSQL full-text search with ranking.
    Falls back to ILIKE search if FTS index is not available.
    """
    import time

    start_time = time.time()
    
    # Try FTS first if enabled and searching content
    if use_fts and search_content:
        try:
            from grimoire.services.fts_service import search_fts
            
            fts_results = await search_fts(
                db, q, 
                game_system=game_system,
                product_type=product_type,
                limit=limit
            )
            
            if fts_results:
                query_time_ms = int((time.time() - start_time) * 1000)
                return {
                    "results": fts_results,
                    "total": len(fts_results),
                    "query_time_ms": query_time_ms,
                    "content_search": True,
                    "search_method": "fts",
                }
        except Exception as e:
            # Fall back to legacy search if FTS fails
            import logging
            logging.warning(f"FTS search failed, falling back to legacy: {e}")

    # Legacy ILIKE search for metadata
    search_term = f"%{q}%"
    query = (
        select(Product)
        .where(
            or_(
                Product.title.ilike(search_term),
                Product.file_name.ilike(search_term),
                Product.publisher.ilike(search_term),
            )
        )
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    )

    if game_system:
        query = query.where(Product.game_system == game_system)

    if product_type:
        query = query.where(Product.product_type == product_type)

    query = query.limit(limit)

    result = await db.execute(query)
    products = list(result.scalars().unique().all())

    from grimoire.api.routes.products import product_to_response

    results = []
    for p in products:
        item = product_to_response(p)
        if search_content:
            snippets = search_in_extracted_text(p, q)
            if snippets:
                item_dict = item.model_dump()
                item_dict["snippets"] = snippets
                results.append(item_dict)
            else:
                results.append(item.model_dump())
        else:
            results.append(item.model_dump())

    if search_content:
        content_query = (
            select(Product)
            .where(Product.text_extracted == True)
            .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
        )

        if game_system:
            content_query = content_query.where(Product.game_system == game_system)
        if product_type:
            content_query = content_query.where(Product.product_type == product_type)

        content_result = await db.execute(content_query)
        content_products = content_result.scalars().unique().all()

        existing_ids = {r.get("id") for r in results}

        for p in content_products:
            if p.id in existing_ids:
                continue

            snippets = search_in_extracted_text(p, q)
            if snippets:
                item = product_to_response(p)
                item_dict = item.model_dump()
                item_dict["snippets"] = snippets
                results.append(item_dict)

                if len(results) >= limit:
                    break

    query_time_ms = int((time.time() - start_time) * 1000)

    return {
        "results": results[:limit],
        "total": len(results),
        "query_time_ms": query_time_ms,
        "content_search": search_content,
        "search_method": "legacy",
    }
