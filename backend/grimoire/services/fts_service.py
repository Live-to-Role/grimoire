"""Full-text search service - manages SQLite FTS5 indexing."""

import json
import logging
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from grimoire.models import Product, ProductEmbedding

logger = logging.getLogger(__name__)

# Cache FTS availability to avoid repeated sqlite_master queries
_fts_available_cache: bool | None = None

# Under prefix matching ("term"*) these match a large slice of the index while
# carrying almost no signal: "a"* alone turned a 0.02s FTS query into 1.3s.
# Dropping them is both faster and more precise.
_FTS_STOPWORDS = frozenset({
    "a", "an", "the", "of", "on", "in", "to", "for", "and", "or", "with",
    "at", "by", "from", "as", "is", "it", "an",
})


def build_fts_match(query: str) -> str | None:
    """Build an FTS5 MATCH expression from a natural-language query.

    Drops stopwords and single characters (see _FTS_STOPWORDS), prefix-matches
    each remaining term, and ORs them for recall. Embedded quotes are stripped
    so a term can't break out of its quoted token. Returns None when the query
    has no usable content; if every term is a stopword it falls back to the raw
    terms rather than returning an empty match.
    """
    raw = [t for t in query.strip().split() if t]
    terms = [t for t in raw if len(t) > 1 and t.lower() not in _FTS_STOPWORDS]
    if not terms:
        terms = raw
    if not terms:
        return None
    return " OR ".join(f'"{t.replace(chr(34), "")}"*' for t in terms)


async def fts_candidates(
    db: AsyncSession,
    query: str,
    *,
    game_system: str | None = None,
    product_type: str | None = None,
    limit: int = 150,
) -> list[tuple[int, float]]:
    """Lean FTS candidates for hybrid search: (product_id, bm25_magnitude) only.

    The hybrid search flow uses just the id and score, so this skips the
    snippet() extraction over the full-text column and the hydration of every
    matched Product that search_fts does for the UI - that discarded work was
    the dominant cost of a hybrid search (seconds per query).
    """
    match = build_fts_match(query)
    if match is None:
        return []
    # The unary + on the boolean columns is load-bearing: without it SQLite
    # drives the join from ix_products_is_duplicate and re-runs the FTS MATCH
    # once per product (~19k times, ~87s). + disqualifies those indexes so the
    # MATCH drives and products is a primary-key lookup (~0.03s). Do not remove.
    sql = text("""
        SELECT fts.rowid AS product_id, bm25(products_fts) AS rank
        FROM products_fts fts
        JOIN products p ON p.id = fts.rowid
        WHERE products_fts MATCH :query
        AND +p.is_duplicate = 0
        AND +p.is_missing = 0
        AND (:game_system IS NULL OR p.game_system = :game_system)
        AND (:product_type IS NULL OR p.product_type = :product_type)
        ORDER BY rank
        LIMIT :limit
    """)
    try:
        result = await db.execute(sql, {
            "query": match,
            "game_system": game_system,
            "product_type": product_type,
            "limit": limit,
        })
        # bm25 is negative (more negative = better); callers expect a magnitude.
        return [(row[0], abs(row[1])) for row in result.fetchall()]
    except Exception as e:
        logger.warning(f"FTS candidate search failed: {e}")
        return []


async def chunk_candidates(
    db: AsyncSession,
    query: str,
    *,
    game_system: str | None = None,
    product_type: str | None = None,
    limit: int = 150,
) -> list[tuple[int, float, str, int | None]]:
    """Candidate products from the body index, best chunk each.

    Returns (product_id, score, snippet, page_start) sorted by score
    descending. A product is scored by its single best chunk, matching
    TOP_K_CHUNKS = 1 on the semantic side.

    ⚠️ NOT wired into search_service, on purpose. Blending these hits into
    topical ranking was measured and made search worse (precision 84% -> 32%);
    see the comment in search_service.search. This is for explicit phrase
    lookup — "where does this book say X, and on what page".

    ⚠️ Cost scales with how common the terms are, because every matching chunk
    across 3.3M rows is scored before the best-per-product reduction. Measured
    on the live library: a rare term ("Kurabanda") is 0.005s, but "wizard spell
    cards" is 2.6s. Fine for a deliberate lookup, far too slow for a hot path.
    """
    match = build_fts_match(query)
    if match is None:
        return []

    # The unary + on the boolean columns is load-bearing: without it SQLite
    # drives the join from ix_products_is_duplicate and re-runs the FTS MATCH
    # once per product. + disqualifies those indexes so the MATCH drives. Same
    # reasoning as fts_candidates above. Do not remove.
    #
    # bm25() cannot be wrapped in an aggregate — it is an FTS5 auxiliary
    # function and only works directly against the MATCH query ("unable to use
    # function bm25 in the requested context"). So the inner query scores
    # chunks and the outer one reduces them to the best chunk per product.
    # MIN() works there because rank is an ordinary column by that point, and
    # snippet/page_start ride along by SQLite's bare-column rule, which pairs
    # them with the row MIN() chose.
    #
    # The inner LIMIT bounds the work: a common term matches far more chunks
    # than there are products worth returning, and without it every match is
    # materialised before grouping. Taking the globally best-scoring chunks
    # first can in principle drop a product whose best chunk ranks below all
    # of them, but such a product is by construction not in the top `limit`.
    sql = text("""
        SELECT product_id, MIN(rank) AS rank, snippet, page_start
        FROM (
            SELECT
                f.product_id AS product_id,
                bm25(product_chunks_fts) AS rank,
                snippet(product_chunks_fts, 0, '<mark>', '</mark>', '...', 32) AS snippet,
                f.page_start AS page_start
            FROM product_chunks_fts f
            JOIN products p ON p.id = f.product_id
            WHERE product_chunks_fts MATCH :query
            AND +p.is_duplicate = 0
            AND +p.is_missing = 0
            AND (:game_system IS NULL OR p.game_system = :game_system)
            AND (:product_type IS NULL OR p.product_type = :product_type)
            ORDER BY rank
            LIMIT :inner_limit
        )
        GROUP BY product_id
        ORDER BY rank
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, {
            "query": match,
            "game_system": game_system,
            "product_type": product_type,
            "limit": limit,
            "inner_limit": limit * 20,
        })
        # bm25 is negative (more negative = better); callers expect a magnitude.
        return [
            (row[0], abs(row[1]), row[2] or "", row[3])
            for row in result.fetchall()
        ]
    except Exception as e:
        logger.warning(f"Chunk FTS candidate search failed: {e}")
        return []


async def update_search_vector(db: AsyncSession, product: Product) -> bool:
    """Refresh a product's metadata row in the FTS index.

    The body is no longer written here. It lives in product_chunks_fts, keyed
    by chunk and carrying page numbers, written by index_product_chunks. This
    function used to read the extraction JSON and index its first 50,000
    characters, which hid 71% of the library's text from keyword search.

    Args:
        db: Database session
        product: Product to update

    Returns:
        True if successful, False otherwise
    """
    try:
        await db.execute(
            text("DELETE FROM products_fts WHERE rowid = :product_id"),
            {"product_id": product.id}
        )

        await db.execute(
            text("""
                INSERT INTO products_fts(rowid, title, file_name, publisher,
                                         game_system, product_type, description)
                VALUES (:product_id, :title, :file_name, :publisher,
                        :game_system, :product_type, :description)
            """),
            {
                "product_id": product.id,
                "title": product.title or "",
                "file_name": product.file_name or "",
                "publisher": product.publisher or "",
                "game_system": product.game_system or "",
                "product_type": product.product_type or "",
                "description": product.description or "",
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
    """Keyword search over product metadata AND document body text.

    Backs the Library's "search content" toggle
    (`/search?search_content=true`). Metadata comes from products_fts; the body
    comes from product_chunks_fts, which is the whole document rather than the
    first 50,000 characters products_fts used to hold.

    ⚠️ Cost scales with how common the query terms are, because every matching
    chunk across 3.3M rows is scored before the best-per-product reduction.
    Measured on the live library at limit=20, steady state: "Kurabanda" 0.004s,
    "dungeon" 0.67s, "wizard spell cards" 2.5s. The toggle is opt-in and off by
    default, so this is paid only when asked for — but it is slower than the
    old truncated-body search, which only had 19k rows to look at.

    Args:
        db: Database session
        query: Search query string
        game_system: Optional filter by game system
        product_type: Optional filter by product type
        limit: Maximum results

    Returns:
        List of matching products with relevance scores. Body matches also
        carry `snippet` and `matched_page`.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from grimoire.models import ProductTag
    
    # Shared builder: drops stopwords/single chars that explode under prefix
    # matching, and escapes embedded quotes.
    fts_query = build_fts_match(query)
    if fts_query is None:
        return []

    # SQLite FTS5 search with BM25 ranking. The unary + on the boolean columns
    # is load-bearing: without it SQLite drives the join from
    # ix_products_is_duplicate and re-runs the MATCH once per product (~87s);
    # + forces the MATCH to drive (~0.03s). Do not remove. See fts_candidates.
    sql = text("""
        SELECT
            fts.rowid as product_id,
            bm25(products_fts) as rank,
            -- Column 0 is title. This used to be column 6, extracted_text,
            -- which no longer exists: the body moved to product_chunks_fts.
            -- A stale offset here would not error, it would quietly snippet
            -- whichever column now sits at 6. For a body snippet, use
            -- chunk_candidates, which returns one with its page.
            snippet(products_fts, 0, '<mark>', '</mark>', '...', 32) as snippet
        FROM products_fts fts
        JOIN products p ON p.id = fts.rowid
        WHERE products_fts MATCH :query
        AND +p.is_duplicate = 0
        AND +p.is_missing = 0
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
        rows = []

    # This function backs the Library's "search content" toggle, so the body
    # is a first-class source here — unlike search_service, where blending
    # body hits into topical ranking was measured and made results worse.
    # There is no semantic ranking to pollute on this path: the user typed a
    # term and asked which documents contain it.
    body_hits = await chunk_candidates(
        db, query,
        game_system=game_system,
        product_type=product_type,
        limit=limit,
    )

    # (score, snippet, page) per product. bm25 magnitudes from the two tables
    # are not on the same scale, so ordering between a title-only and a
    # body-only match is approximate. Both are real matches; which of them
    # sorts first is a weaker claim than that they both appear.
    merged: dict[int, tuple[float, str | None, int | None]] = {}
    for row in rows:
        merged[row[0]] = (abs(row[1]), row[2] if len(row) > 2 else None, None)
    for pid, score, snippet, page in body_hits:
        prev_score = merged[pid][0] if pid in merged else 0.0
        # The body snippet wins: on this path it is the thing being searched
        # for, and it is the only one that can carry a page.
        merged[pid] = (max(prev_score, score), snippet or None, page)

    if not merged:
        return []

    product_ids = [
        pid for pid, _ in sorted(merged.items(), key=lambda kv: -kv[1][0])
    ][:limit]
    rank_map = {pid: merged[pid] for pid in product_ids}

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
        
        rank, snippet, page = rank_map.get(product_id, (0, None, None))
        item = product_to_response(product).model_dump()
        item["relevance_score"] = float(rank)
        if snippet:
            item["snippet"] = snippet
        if page is not None:
            # Same field the semantic path uses, so the Library renders these
            # the same way ("p. 32: ...").
            item["matched_page"] = page
        results.append(item)
    
    return results


async def check_fts_available(db: AsyncSession) -> bool:
    """Check if FTS5 table exists (cached after first check)."""
    global _fts_available_cache
    
    if _fts_available_cache is not None:
        return _fts_available_cache
    
    try:
        result = await db.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='products_fts'")
        )
        _fts_available_cache = result.fetchone() is not None
        return _fts_available_cache
    except Exception:
        _fts_available_cache = False
        return False


async def clear_product_chunk_index(db: AsyncSession, product_id: int) -> None:
    """Remove a product's rows from the body index.

    ⚠️ Must run BEFORE the product's product_embeddings rows are deleted. The
    FTS rowid is the embedding id, so this resolves rowids through
    product_embeddings; once those rows are gone it matches nothing and leaves
    orphans behind. prune_orphaned_chunk_index() is the safety net.

    Deleting by rowid rather than by product_id is not a micro-optimisation:
    product_id is UNINDEXED, so filtering on it scans every row in a 3.3M-row
    table.
    """
    await db.execute(
        text("""
            DELETE FROM product_chunks_fts
            WHERE rowid IN (
                SELECT id FROM product_embeddings WHERE product_id = :product_id
            )
        """),
        {"product_id": product_id},
    )


async def index_product_chunks(db: AsyncSession, product_id: int) -> int:
    """Mirror a product's chunk text into the body index. Returns rows written.

    Deliberately not a database trigger. Trigger-maintained indexing is what
    produced dc377a7: the trigger drifted from the schema it served, blanked
    2,800 products' text, and went unnoticed for months because nothing
    errored. An explicit write path is testable.
    """
    rows = (await db.execute(
        select(
            ProductEmbedding.id,
            ProductEmbedding.chunk_index,
            ProductEmbedding.chunk_text,
            ProductEmbedding.page_start,
            ProductEmbedding.page_end,
        )
        .where(ProductEmbedding.product_id == product_id)
        .order_by(ProductEmbedding.chunk_index)
    )).all()

    for row_id, chunk_index, chunk_text, page_start, page_end in rows:
        await db.execute(
            text("""
                INSERT INTO product_chunks_fts(
                    rowid, chunk_text, product_id, chunk_index, page_start, page_end
                ) VALUES (:rowid, :chunk_text, :product_id, :chunk_index, :page_start, :page_end)
            """),
            {
                "rowid": row_id,
                "chunk_text": chunk_text,
                "product_id": product_id,
                "chunk_index": chunk_index,
                "page_start": page_start,
                "page_end": page_end,
            },
        )

    return len(rows)


async def prune_orphaned_chunk_index(db: AsyncSession) -> int:
    """Drop body-index rows whose chunk no longer exists. Returns rows removed.

    Products are deleted from four call sites, and their product_embeddings go
    with them by ORM delete-orphan. A virtual table has no relationship to
    ride, and SQLite foreign keys are off, so nothing removes these rows
    automatically. Sweeping is deliberate: hooking every delete site is the
    fragility that produced dc377a7, and a fifth site added later would leak
    silently.

    This is a full scan of the index. It is a maintenance operation, not
    something to call per request.
    """
    result = await db.execute(text("""
        DELETE FROM product_chunks_fts
        WHERE rowid NOT IN (SELECT id FROM product_embeddings)
    """))
    await db.commit()
    return result.rowcount or 0
