"""Semantic search API endpoints."""

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, delete

from grimoire.api.deps import DbSession
from grimoire.models import Product, ProductEmbedding
from grimoire.services.processor import get_extracted_text
from grimoire.services.embeddings import (
    generate_embeddings,
    find_similar,
    SENTENCE_TRANSFORMERS_AVAILABLE,
)
from grimoire.processors.ai_identifier import (
    get_setting_from_db,
    check_ollama_available,
    get_ollama_url,
)


router = APIRouter()


async def check_provider_available(provider: str) -> bool:
    """Check if a specific embedding provider is available."""
    if provider == "none":
        return False
    providers = await _get_embedding_providers()
    return providers.get(provider, False)


async def _count_embedded_products(db) -> int:
    """Count products that have embeddings."""
    result = await db.execute(
        select(ProductEmbedding.product_id).distinct()
    )
    return len(result.scalars().all())


async def _get_embedding_providers() -> dict[str, bool]:
    """Check embedding provider availability from env vars AND database settings."""
    import os

    openai_available = bool(os.getenv("OPENAI_API_KEY"))
    if not openai_available:
        openai_available = bool(await get_setting_from_db("openai_api_key"))

    ollama_url = await get_ollama_url()
    ollama_available = check_ollama_available(ollama_url)

    return {
        "openai": openai_available,
        "ollama": ollama_available,
        "local": SENTENCE_TRANSFORMERS_AVAILABLE,
    }



class EmbedProductRequest(BaseModel):
    """Request to generate embeddings for a product."""
    provider: str | None = Field(None, description="Embedding provider (openai, local)")
    model: str | None = Field(None, description="Specific model to use")
    chunk_size: int = Field(1000, ge=100, le=2000)
    overlap: int = Field(100, ge=0, le=200)


class SemanticSearchRequest(BaseModel):
    """Request for semantic search."""
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(10, ge=1, le=100)
    threshold: float = Field(0.5, ge=0.0, le=1.0)
    provider: str | None = Field(None)
    model: str | None = Field(None)
    # Metadata filters (applied post-vector-search)
    game_system: str | None = Field(None)
    product_type: str | None = Field(None)
    genre: str | None = Field(None)
    publisher: str | None = Field(None)
    author: str | None = Field(None)
    level_min: int | None = Field(None, ge=0)
    level_max: int | None = Field(None, ge=0)
    tags: str | None = Field(None, description="Comma-separated tag IDs")
    collection: int | None = Field(None)
    hybrid: bool = Field(False, description="Blend keyword (BM25) + vector scores")


def build_semantic_filter_conditions(request: SemanticSearchRequest) -> list:
    """Build SQLAlchemy filter conditions from semantic search request."""
    conditions = []
    if request.game_system:
        conditions.append(Product.game_system == request.game_system)
    if request.product_type:
        conditions.append(Product.product_type == request.product_type)
    if request.genre:
        conditions.append(Product.genre == request.genre)
    if request.publisher:
        conditions.append(Product.publisher == request.publisher)
    if request.author:
        conditions.append(Product.author == request.author)
    if request.level_min is not None:
        conditions.append(
            (Product.level_range_max >= request.level_min) | (Product.level_range_max.is_(None))
        )
    if request.level_max is not None:
        conditions.append(
            (Product.level_range_min <= request.level_max) | (Product.level_range_min.is_(None))
        )
    return conditions


class NaturalLanguageQueryRequest(BaseModel):
    """Request for natural language query."""
    query: str = Field(..., min_length=1, max_length=500, description="Natural language query like 'Find swamp adventures for level 3'")
    top_k: int = Field(10, ge=1, le=50)
    ai_provider: str | None = Field(None, description="AI provider for query interpretation")
    embedding_provider: str | None = Field(None, description="Embedding provider for search")


@router.get("/providers")
async def get_embedding_providers() -> dict:
    """Get available embedding providers."""
    return {
        "providers": await _get_embedding_providers(),
    }


@router.get("/search-status")
async def semantic_search_status(db: DbSession) -> dict:
    """Lightweight status check for the Library search bar."""
    import json
    from grimoire.models import Setting

    # Read semantic_search_provider setting
    result = await db.execute(
        select(Setting).where(Setting.key == "semantic_search_provider")
    )
    setting = result.scalar_one_or_none()
    provider = json.loads(setting.value) if setting else "none"

    if provider == "none":
        return {
            "enabled": False,
            "provider": "none",
            "has_embeddings": False,
            "embedded_count": 0,
        }

    available = await check_provider_available(provider)
    embedded_count = await _count_embedded_products(db)

    return {
        "enabled": available and embedded_count > 0,
        "provider": provider,
        "has_embeddings": embedded_count > 0,
        "embedded_count": embedded_count,
    }


@router.post("/embed/{product_id}")
async def embed_product(
    db: DbSession,
    product_id: int,
    request: EmbedProductRequest,
) -> dict:
    """Generate and store embeddings for a product's content."""
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    text = get_extracted_text(product)
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Product has no extracted text"
        )

    from grimoire.services.processor import get_extracted_pages
    from grimoire.services.embeddings import build_metadata_preamble, build_chunks_for_product
    pages = get_extracted_pages(product)
    preamble = build_metadata_preamble(product)
    chunk_tuples = build_chunks_for_product(
        preamble, pages, text, request.chunk_size, request.overlap
    )

    # Delete existing embeddings
    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
    )

    # Generate embeddings
    try:
        embeddings = await generate_embeddings(
            [c for c, _, _ in chunk_tuples], request.provider, request.model
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Store embeddings
    for i, ((chunk, page_start, page_end), emb_result) in enumerate(zip(chunk_tuples, embeddings)):
        embedding_record = ProductEmbedding(
            product_id=product_id,
            chunk_index=i,
            chunk_text=chunk[:1000],  # Store truncated for reference
            embedding_model=emb_result.model,
            embedding_dim=len(emb_result.embedding),
            page_start=page_start,
            page_end=page_end,
        )
        embedding_record.set_embedding_vector(emb_result.embedding)
        db.add(embedding_record)

    # Compute and store per-product averaged vector
    from grimoire.models.product_search_vector import ProductSearchVector, compute_weighted_average_vector
    from grimoire.services.embeddings import invalidate_vector_cache

    chunk_vectors = [emb_result.embedding for emb_result in embeddings]
    avg_vector = compute_weighted_average_vector(chunk_vectors, metadata_weight=2.0)

    existing_sv = await db.execute(
        select(ProductSearchVector).where(ProductSearchVector.product_id == product_id)
    )
    sv = existing_sv.scalar_one_or_none()
    if sv:
        sv.set_vector(avg_vector)
        sv.embedding_model = embeddings[0].model
    else:
        sv = ProductSearchVector(
            product_id=product_id,
            embedding_model=embeddings[0].model,
            embedding_dim=len(avg_vector),
        )
        sv.set_vector(avg_vector)
        db.add(sv)

    await db.commit()
    invalidate_vector_cache()

    return {
        "product_id": product_id,
        "chunks_embedded": len(chunk_tuples),
        "model": embeddings[0].model if embeddings else None,
        "embedding_dim": len(embeddings[0].embedding) if embeddings else None,
    }


@router.post("/search")
async def semantic_search(
    db: DbSession,
    request: SemanticSearchRequest,
) -> dict:
    """Search products using semantic similarity with per-product vectors."""
    import json
    import logging
    import traceback
    from grimoire.models import Setting
    from grimoire.models.product_search_vector import ProductSearchVector
    from grimoire.services.embeddings import search_product_vectors
    from grimoire.api.routes.products import product_to_response
    from sqlalchemy.orm import selectinload
    from grimoire.models import ProductTag

    logger = logging.getLogger(__name__)

    try:
        # Read provider from settings (ignore request param)
        result = await db.execute(
            select(Setting).where(Setting.key == "semantic_search_provider")
        )
        setting = result.scalar_one_or_none()
        provider = json.loads(setting.value) if setting else "none"

        if provider == "none":
            raise HTTPException(status_code=400, detail="Semantic search not configured. Set a search provider in Settings.")

        # Embed the query
        try:
            query_embeddings = await generate_embeddings(
                [request.query], provider, request.model
            )
            query_vector = query_embeddings[0].embedding
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

        # Load per-product vectors
        sv_result = await db.execute(select(ProductSearchVector))
        search_vectors = {sv.product_id: sv.get_vector() for sv in sv_result.scalars().all()}

        if not search_vectors:
            return {"query": request.query, "results": [], "total_matches": 0}

        # Build filter conditions
        filter_conditions = build_semantic_filter_conditions(request)

        # Handle tag filtering via subquery
        if request.tags:
            tag_ids = [int(t.strip()) for t in request.tags.split(",") if t.strip()]
            if tag_ids:
                tag_subq = select(ProductTag.product_id).where(ProductTag.tag_id.in_(tag_ids))
                filter_conditions.append(Product.id.in_(tag_subq))

        # Handle collection filtering via subquery
        if request.collection:
            from grimoire.models.collection import CollectionProduct
            coll_subq = select(CollectionProduct.product_id).where(
                CollectionProduct.collection_id == request.collection
            )
            filter_conditions.append(Product.id.in_(coll_subq))

        # Fetch more candidates than requested since filters will reduce results
        search_top_k = request.top_k * 3 if filter_conditions else request.top_k

        # Fast numpy search
        matches = search_product_vectors(
            query_vector, search_vectors, search_top_k, request.threshold
        )

        # Hybrid: blend with BM25 keyword results
        if request.hybrid and request.query:
            from grimoire.services.fts_service import search_fts
            from grimoire.services.hybrid_search import reciprocal_rank_fusion

            try:
                fts_results = await search_fts(
                    db, request.query,
                    game_system=request.game_system,
                    product_type=request.product_type,
                    limit=request.top_k * 3,
                )
                keyword_matches = [
                    (r["id"], r["relevance_score"]) for r in fts_results
                ]
            except Exception:
                logger.warning("FTS5 search failed during hybrid search, falling back to pure semantic")
                keyword_matches = []

            # Fuse rankings
            matches = reciprocal_rank_fusion(matches, keyword_matches)
            matches = matches[:search_top_k]

            # Normalize RRF scores to 0-1 range for consistent UI display
            if matches:
                max_score = matches[0][1]
                if max_score > 0:
                    matches = [(pid, score / max_score) for pid, score in matches]

        # Fetch full product data for matched IDs, applying filters
        matched_ids = [pid for pid, _ in matches]
        score_map = {pid: score for pid, score in matches}

        if not matched_ids:
            return {"query": request.query, "results": [], "total_matches": 0}

        products_query = (
            select(Product)
            .where(Product.id.in_(matched_ids))
            .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
        )
        if filter_conditions:
            products_query = products_query.where(*filter_conditions)
        products_result = await db.execute(products_query)
        products = {p.id: p for p in products_result.scalars().all()}

        results = []
        for product_id in matched_ids:
            product = products.get(product_id)
            if not product:
                continue
            item = product_to_response(product).model_dump()
            item["score"] = round(score_map[product_id], 4)
            results.append(item)

        results = results[:request.top_k]

        return {
            "query": request.query,
            "results": results,
            "total_matches": len(results),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Semantic search failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Semantic search error: {e}")


@router.post("/embed-batch")
async def embed_batch(
    db: DbSession,
    product_ids: list[int] = Query(..., description="Product IDs to embed"),
    provider: str | None = Query(None),
    model: str | None = Query(None),
    chunk_size: int = Query(1000, ge=100, le=2000),
) -> dict:
    """Generate embeddings for multiple products."""
    success = 0
    failed = 0
    skipped = 0
    
    for product_id in product_ids:
        query = select(Product).where(Product.id == product_id)
        result = await db.execute(query)
        product = result.scalar_one_or_none()
        
        if not product:
            failed += 1
            continue
        
        text = get_extracted_text(product)
        if not text:
            skipped += 1
            continue
        
        try:
            # Delete existing embeddings
            await db.execute(
                delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
            )

            from grimoire.services.processor import get_extracted_pages
            from grimoire.services.embeddings import build_metadata_preamble, build_chunks_for_product
            pages = get_extracted_pages(product)
            chunk_tuples = build_chunks_for_product(
                build_metadata_preamble(product), pages, text, chunk_size, 100
            )
            embeddings = await generate_embeddings(
                [c for c, _, _ in chunk_tuples], provider, model
            )

            for i, ((chunk, page_start, page_end), emb_result) in enumerate(zip(chunk_tuples, embeddings)):
                embedding_record = ProductEmbedding(
                    product_id=product_id,
                    chunk_index=i,
                    chunk_text=chunk[:1000],
                    embedding_model=emb_result.model,
                    embedding_dim=len(emb_result.embedding),
                    page_start=page_start,
                    page_end=page_end,
                )
                embedding_record.set_embedding_vector(emb_result.embedding)
                db.add(embedding_record)

            # Compute and store per-product averaged vector
            from grimoire.models.product_search_vector import ProductSearchVector, compute_weighted_average_vector
            from grimoire.services.embeddings import invalidate_vector_cache

            chunk_vectors = [emb_result.embedding for emb_result in embeddings]
            avg_vector = compute_weighted_average_vector(chunk_vectors, metadata_weight=2.0)

            existing_sv = await db.execute(
                select(ProductSearchVector).where(ProductSearchVector.product_id == product_id)
            )
            sv = existing_sv.scalar_one_or_none()
            if sv:
                sv.set_vector(avg_vector)
                sv.embedding_model = embeddings[0].model
            else:
                sv = ProductSearchVector(
                    product_id=product_id,
                    embedding_model=embeddings[0].model,
                    embedding_dim=len(avg_vector),
                )
                sv.set_vector(avg_vector)
                db.add(sv)

            await db.commit()
            invalidate_vector_cache()
            success += 1
        except Exception as e:
            failed += 1
            import logging
            logging.error(f"Failed to embed product {product_id}: {e}")

    return {
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "total": len(product_ids),
    }


@router.post("/embed-all")
async def embed_all_products(
    db: DbSession,
    provider: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    """Queue all products with extracted text for embedding generation."""
    # Check if any embedding provider is available
    providers = await _get_embedding_providers()
    if not any(providers.values()):
        raise HTTPException(
            status_code=400,
            detail="No embedding provider available. Install sentence-transformers for local embeddings, configure OLLAMA_BASE_URL, or set OPENAI_API_KEY."
        )
    
    # Find products with text but no embeddings
    embedded_query = select(ProductEmbedding.product_id).distinct()
    embedded_result = await db.execute(embedded_query)
    embedded_ids = set(embedded_result.scalars().all())
    
    # Build query for products that need embedding
    products_query = select(Product).where(Product.text_extracted == True)
    if embedded_ids:
        products_query = products_query.where(Product.id.notin_(embedded_ids))
    products_query = products_query.limit(limit)
    
    result = await db.execute(products_query)
    products = list(result.scalars().all())
    
    if not products:
        return {
            "message": "All products with extracted text already have embeddings",
            "queued": 0,
        }
    
    # Queue for embedding (using ProcessingQueue)
    from grimoire.models import ProcessingQueue
    
    queued = 0
    for product in products:
        existing = await db.execute(
            select(ProcessingQueue.id).where(
                ProcessingQueue.product_id == product.id,
                ProcessingQueue.task_type == "embed",
                ProcessingQueue.status.in_(["pending", "processing"])
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            continue
        
        item = ProcessingQueue(
            product_id=product.id,
            task_type="embed",
            priority=9,  # Low priority
            status="pending",
        )
        db.add(item)
        queued += 1
    
    await db.commit()
    
    return {
        "message": f"Queued {queued} products for embedding generation",
        "queued": queued,
        "provider": provider or "auto",
    }


@router.post("/re-embed-mismatched")
async def re_embed_mismatched(
    db: DbSession,
    target_model: str = Query("nomic-embed-text", description="Target embedding model"),
) -> dict:
    """Queue products whose search vectors don't match the target model for re-embedding."""
    from grimoire.models.product_search_vector import ProductSearchVector
    from grimoire.models import ProcessingQueue

    # Find product IDs with wrong model
    result = await db.execute(
        select(ProductSearchVector.product_id).where(
            ProductSearchVector.embedding_model != target_model
        )
    )
    mismatched_ids = result.scalars().all()

    if not mismatched_ids:
        return {"message": "All vectors already match target model", "queued": 0}

    # Delete old embeddings + search vectors so they get re-generated
    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id.in_(mismatched_ids))
    )
    await db.execute(
        delete(ProductSearchVector).where(ProductSearchVector.product_id.in_(mismatched_ids))
    )

    # Queue for re-embedding
    queued = 0
    for pid in mismatched_ids:
        existing = await db.execute(
            select(ProcessingQueue.id).where(
                ProcessingQueue.product_id == pid,
                ProcessingQueue.task_type == "embed",
                ProcessingQueue.status.in_(["pending", "processing"]),
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            continue
        db.add(ProcessingQueue(
            product_id=pid,
            task_type="embed",
            priority=9,
            status="pending",
        ))
        queued += 1

    await db.commit()

    return {
        "message": f"Queued {queued} products for re-embedding with {target_model}",
        "queued": queued,
        "deleted_old": len(mismatched_ids),
        "target_model": target_model,
    }


@router.get("/status")
async def embedding_status(db: DbSession) -> dict:
    """Get embedding status for products with extracted text."""
    import os
    from grimoire.models import ProcessingQueue

    # Count products with embeddings
    emb_query = select(ProductEmbedding.product_id).distinct()
    emb_result = await db.execute(emb_query)
    embedded_products = set(emb_result.scalars().all())

    # Count products that CAN be embedded (have text extracted)
    prod_query = select(Product.id).where(Product.text_extracted == True)
    prod_result = await db.execute(prod_query)
    embeddable_products = set(prod_result.scalars().all())

    # Get available providers (check env vars AND database settings)
    providers = await _get_embedding_providers()
    any_provider_available = any(providers.values())

    # Queue stats for embed tasks
    from sqlalchemy import func as sql_func
    queue_stats_query = (
        select(ProcessingQueue.status, sql_func.count())
        .where(ProcessingQueue.task_type == "embed")
        .group_by(ProcessingQueue.status)
    )
    queue_result = await db.execute(queue_stats_query)
    queue_counts = dict(queue_result.all())

    # Get last error message from failed embed tasks
    last_error_query = (
        select(ProcessingQueue.error_message)
        .where(
            ProcessingQueue.task_type == "embed",
            ProcessingQueue.status == "failed",
            ProcessingQueue.error_message.isnot(None),
        )
        .order_by(ProcessingQueue.completed_at.desc())
        .limit(1)
    )
    last_error_result = await db.execute(last_error_query)
    last_error = last_error_result.scalar_one_or_none()

    # Anthropic availability (for NL query interpretation, not embeddings)
    anthropic_available = bool(os.getenv("ANTHROPIC_API_KEY", ""))
    if not anthropic_available:
        anthropic_available = bool(await get_setting_from_db("anthropic_api_key"))

    return {
        "total_products": len(embeddable_products),
        "embedded_products": len(embedded_products),
        "not_embedded": len(embeddable_products - embedded_products),
        "coverage_percent": round(len(embedded_products) / len(embeddable_products) * 100, 1) if embeddable_products else 0,
        "providers": providers,
        "provider_available": any_provider_available,
        "anthropic_available": anthropic_available,
        "queue": {
            "pending": queue_counts.get("pending", 0),
            "processing": queue_counts.get("processing", 0),
            "completed": queue_counts.get("completed", 0),
            "failed": queue_counts.get("failed", 0),
            "last_error": last_error,
        },
    }


@router.delete("/embeddings/{product_id}")
async def delete_product_embeddings(
    db: DbSession,
    product_id: int,
) -> dict:
    """Delete embeddings for a product."""
    from grimoire.models.product_search_vector import ProductSearchVector
    from grimoire.services.embeddings import invalidate_vector_cache

    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
    )
    # Also delete the averaged search vector
    await db.execute(
        delete(ProductSearchVector).where(ProductSearchVector.product_id == product_id)
    )
    await db.commit()
    invalidate_vector_cache()

    return {
        "product_id": product_id,
        "deleted": True,
    }


NL_QUERY_PROMPT = """You are a search query interpreter for a TTRPG PDF library.

Convert the user's natural language query into structured search parameters.

Return a JSON object with:
- search_terms: array of key search terms to look for
- filters: object with optional filters:
  - game_system: specific game system (e.g., "D&D 5E", "Pathfinder 2E", "OSR")
  - product_type: type of product (e.g., "Adventure", "Sourcebook", "Monster Manual")
  - level_min: minimum character level (number or null)
  - level_max: maximum character level (number or null)
  - themes: array of themes (e.g., "horror", "wilderness", "dungeon", "urban")
- semantic_query: a refined query string optimized for semantic search

User query: {query}

Return ONLY the JSON object."""


async def interpret_nl_query(query: str, provider: str | None = None) -> dict:
    """Use AI to interpret a natural language query."""
    import json
    import os
    import httpx

    openai_key = os.getenv("OPENAI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    if provider is None:
        if anthropic_key:
            provider = "anthropic"
        elif openai_key:
            provider = "openai"
        else:
            # Return basic interpretation without AI
            return {
                "search_terms": query.lower().split(),
                "filters": {},
                "semantic_query": query,
            }

    prompt = NL_QUERY_PROMPT.format(query=query)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if provider == "openai" and openai_key:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                return json.loads(data["choices"][0]["message"]["content"])

            elif provider == "anthropic" and anthropic_key:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 500,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["content"][0]["text"].strip()
                # Extract JSON
                start = content.find('{')
                end = content.rfind('}')
                if start != -1 and end != -1:
                    return json.loads(content[start:end + 1])

    except Exception as e:
        print(f"NL query interpretation failed: {e}")

    # Fallback
    return {
        "search_terms": query.lower().split(),
        "filters": {},
        "semantic_query": query,
    }


@router.post("/query")
async def natural_language_query(
    db: DbSession,
    request: NaturalLanguageQueryRequest,
) -> dict:
    """
    Search using natural language queries like "Find swamp adventures for level 3".
    Uses AI to interpret the query and semantic search to find results.
    """
    # Interpret the query
    interpretation = await interpret_nl_query(request.query, request.ai_provider)

    # Get semantic query
    semantic_query = interpretation.get("semantic_query", request.query)
    filters = interpretation.get("filters", {})

    # Generate query embedding
    try:
        query_embeddings = await generate_embeddings(
            [semantic_query],
            request.embedding_provider,
        )
        query_vector = query_embeddings[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    # Get stored embeddings
    emb_query = select(ProductEmbedding)
    emb_result = await db.execute(emb_query)
    stored_embeddings = list(emb_result.scalars().all())

    if not stored_embeddings:
        return {
            "query": request.query,
            "interpretation": interpretation,
            "results": [],
            "message": "No embeddings found. Run /embed on products first.",
        }

    # Find similar
    embeddings_list = [
        (emb.id, emb.get_embedding_vector())
        for emb in stored_embeddings
    ]

    similar = find_similar(
        query_vector,
        embeddings_list,
        request.top_k * 3,
        0.4,
    )

    # Get products and apply filters
    seen_products = set()
    results = []

    for emb_id, score in similar:
        emb_record = next((e for e in stored_embeddings if e.id == emb_id), None)
        if not emb_record:
            continue

        product_id = emb_record.product_id
        if product_id in seen_products:
            continue
        seen_products.add(product_id)

        # Get product
        prod_query = select(Product).where(Product.id == product_id)
        prod_result = await db.execute(prod_query)
        product = prod_result.scalar_one_or_none()

        if not product:
            continue

        # Apply filters
        if filters.get("game_system"):
            if product.game_system and filters["game_system"].lower() not in product.game_system.lower():
                continue

        if filters.get("product_type"):
            if product.product_type and filters["product_type"].lower() not in product.product_type.lower():
                continue

        if filters.get("level_min") is not None:
            if product.level_range_max and product.level_range_max < filters["level_min"]:
                continue

        if filters.get("level_max") is not None:
            if product.level_range_min and product.level_range_min > filters["level_max"]:
                continue

        results.append({
            "product_id": product_id,
            "title": product.title or product.file_name,
            "game_system": product.game_system,
            "product_type": product.product_type,
            "level_range": f"{product.level_range_min or '?'}-{product.level_range_max or '?'}" if product.level_range_min or product.level_range_max else None,
            "score": round(score, 4),
            "matched_chunk": emb_record.chunk_text[:150] + "..." if len(emb_record.chunk_text) > 150 else emb_record.chunk_text,
        })

        if len(results) >= request.top_k:
            break

    return {
        "query": request.query,
        "interpretation": interpretation,
        "results": results,
        "total_matches": len(results),
    }


@router.post("/similar/{product_id}")
async def find_similar_products(
    db: DbSession,
    product_id: int,
    top_k: int = Query(5, ge=1, le=20),
) -> dict:
    """Find products similar to a given product."""
    # Get embeddings for the source product
    source_query = select(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
    source_result = await db.execute(source_query)
    source_embeddings = list(source_result.scalars().all())

    if not source_embeddings:
        raise HTTPException(
            status_code=400,
            detail="Product has no embeddings. Run /embed first."
        )

    # Average the source embeddings
    import numpy as np
    source_vectors = [e.get_embedding_vector() for e in source_embeddings]
    avg_vector = np.mean(source_vectors, axis=0).tolist()

    # Get all other embeddings
    other_query = select(ProductEmbedding).where(ProductEmbedding.product_id != product_id)
    other_result = await db.execute(other_query)
    other_embeddings = list(other_result.scalars().all())

    if not other_embeddings:
        return {
            "source_product_id": product_id,
            "similar": [],
            "message": "No other products have embeddings.",
        }

    # Find similar
    embeddings_list = [
        (emb.id, emb.get_embedding_vector())
        for emb in other_embeddings
    ]

    similar = find_similar(avg_vector, embeddings_list, top_k * 3, 0.5)

    # Dedupe by product
    seen_products = set()
    results = []

    for emb_id, score in similar:
        emb_record = next((e for e in other_embeddings if e.id == emb_id), None)
        if not emb_record:
            continue

        pid = emb_record.product_id
        if pid in seen_products:
            continue
        seen_products.add(pid)

        prod_query = select(Product).where(Product.id == pid)
        prod_result = await db.execute(prod_query)
        product = prod_result.scalar_one_or_none()

        if product:
            results.append({
                "product_id": pid,
                "title": product.title or product.file_name,
                "game_system": product.game_system,
                "similarity": round(score, 4),
            })

        if len(results) >= top_k:
            break

    return {
        "source_product_id": product_id,
        "similar": results,
    }
