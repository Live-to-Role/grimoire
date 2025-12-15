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
    chunk_text,
    get_available_providers,
)


router = APIRouter()


class EmbedProductRequest(BaseModel):
    """Request to generate embeddings for a product."""
    provider: str | None = Field(None, description="Embedding provider (openai, local)")
    model: str | None = Field(None, description="Specific model to use")
    chunk_size: int = Field(500, ge=100, le=2000)
    overlap: int = Field(50, ge=0, le=200)


class SemanticSearchRequest(BaseModel):
    """Request for semantic search."""
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(10, ge=1, le=100)
    threshold: float = Field(0.5, ge=0.0, le=1.0)
    provider: str | None = Field(None)
    model: str | None = Field(None)


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
        "providers": get_available_providers(),
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

    # Delete existing embeddings
    await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
    )

    # Chunk the text
    chunks = chunk_text(text, request.chunk_size, request.overlap)

    # Generate embeddings
    try:
        embeddings = await generate_embeddings(chunks, request.provider, request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Store embeddings
    for i, (chunk, emb_result) in enumerate(zip(chunks, embeddings)):
        embedding_record = ProductEmbedding(
            product_id=product_id,
            chunk_index=i,
            chunk_text=chunk[:1000],  # Store truncated for reference
            embedding_model=emb_result.model,
            embedding_dim=len(emb_result.embedding),
        )
        embedding_record.set_embedding_vector(emb_result.embedding)
        db.add(embedding_record)

    await db.commit()

    return {
        "product_id": product_id,
        "chunks_embedded": len(chunks),
        "model": embeddings[0].model if embeddings else None,
        "embedding_dim": len(embeddings[0].embedding) if embeddings else None,
    }


@router.post("/search")
async def semantic_search(
    db: DbSession,
    request: SemanticSearchRequest,
) -> dict:
    """Search products using semantic similarity (in-memory cosine similarity)."""
    # Generate query embedding
    try:
        query_embeddings = await generate_embeddings(
            [request.query],
            request.provider,
            request.model,
        )
        query_vector = query_embeddings[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    # In-memory search using cosine similarity
    emb_query = select(ProductEmbedding)
    emb_result = await db.execute(emb_query)
    stored_embeddings = list(emb_result.scalars().all())

    if not stored_embeddings:
        return {
            "query": request.query,
            "results": [],
            "message": "No embeddings found. Run /embed on products first.",
        }

    # Build embedding list for search
    embeddings_list = [
        (emb.id, emb.get_embedding_vector())
        for emb in stored_embeddings
    ]

    # Find similar using cosine similarity
    similar = find_similar(
        query_vector,
        embeddings_list,
        request.top_k * 2,
        request.threshold,
    )

    # Get product info and dedupe
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

        prod_query = select(Product).where(Product.id == product_id)
        prod_result = await db.execute(prod_query)
        product = prod_result.scalar_one_or_none()

        if product:
            results.append({
                "product_id": product_id,
                "title": product.title or product.file_name,
                "score": round(score, 4),
                "matched_chunk": emb_record.chunk_text[:200] + "..." if len(emb_record.chunk_text) > 200 else emb_record.chunk_text,
            })

        if len(results) >= request.top_k:
            break

    return {
        "query": request.query,
        "results": results,
        "total_matches": len(results),
    }


@router.post("/embed-batch")
async def embed_batch(
    db: DbSession,
    product_ids: list[int] = Query(..., description="Product IDs to embed"),
    provider: str | None = Query(None),
    model: str | None = Query(None),
    chunk_size: int = Query(500, ge=100, le=2000),
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
            
            chunks = chunk_text(text, chunk_size, 50)
            embeddings = await generate_embeddings(chunks, provider, model)
            
            for i, (chunk, emb_result) in enumerate(zip(chunks, embeddings)):
                embedding_record = ProductEmbedding(
                    product_id=product_id,
                    chunk_index=i,
                    chunk_text=chunk[:1000],
                    embedding_model=emb_result.model,
                    embedding_dim=len(emb_result.embedding),
                )
                embedding_record.set_embedding_vector(emb_result.embedding)
                db.add(embedding_record)
            
            await db.commit()
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
    from sqlalchemy import func
    
    # Find products with text but no embeddings
    embedded_query = select(ProductEmbedding.product_id).distinct()
    embedded_result = await db.execute(embedded_query)
    embedded_ids = set(embedded_result.scalars().all())
    
    products_query = select(Product).where(
        Product.text_extracted == True,
        Product.id.notin_(embedded_ids) if embedded_ids else True,
    ).limit(limit)
    
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
            select(ProcessingQueue).where(
                ProcessingQueue.product_id == product.id,
                ProcessingQueue.task_type == "embed",
                ProcessingQueue.status.in_(["pending", "processing"])
            )
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


@router.get("/status")
async def embedding_status(db: DbSession) -> dict:
    """Get embedding status for all products."""
    # Count products with embeddings
    emb_query = select(ProductEmbedding.product_id).distinct()
    emb_result = await db.execute(emb_query)
    embedded_products = set(emb_result.scalars().all())

    # Count total products
    prod_query = select(Product.id)
    prod_result = await db.execute(prod_query)
    all_products = set(prod_result.scalars().all())

    return {
        "total_products": len(all_products),
        "embedded_products": len(embedded_products),
        "not_embedded": len(all_products - embedded_products),
        "coverage_percent": round(len(embedded_products) / len(all_products) * 100, 1) if all_products else 0,
    }


@router.delete("/embeddings/{product_id}")
async def delete_product_embeddings(
    db: DbSession,
    product_id: int,
) -> dict:
    """Delete embeddings for a product."""
    result = await db.execute(
        delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
    )
    await db.commit()

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
                        "model": "claude-3-haiku-20240307",
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
