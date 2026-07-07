"""
Vector embeddings service for semantic search.
Supports OpenAI, Ollama, and local sentence-transformers embeddings.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from sqlalchemy import inspect

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# Local model instance (lazy loaded)
_local_model = None


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""
    embedding: list[float]
    model: str
    token_count: int | None = None


def get_local_model():
    """Get or initialize the local embedding model."""
    global _local_model
    if _local_model is None and SENTENCE_TRANSFORMERS_AVAILABLE:
        # Use a small, fast model good for semantic search
        _local_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _local_model


async def embed_with_openai(
    texts: list[str],
    api_key: str,
    model: str = "text-embedding-3-small",
) -> list[EmbeddingResult]:
    """Generate embeddings using OpenAI API."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": texts,
            },
        )
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data["data"]:
            results.append(EmbeddingResult(
                embedding=item["embedding"],
                model=model,
                token_count=data.get("usage", {}).get("total_tokens"),
            ))
        return results


def embed_with_local(
    texts: list[str],
    model_name: str = "all-MiniLM-L6-v2",
) -> list[EmbeddingResult]:
    """Generate embeddings using local sentence-transformers model."""
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        raise ImportError("sentence-transformers not installed")

    model = get_local_model()
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        batch_size=32,
        normalize_embeddings=True,
    )

    results = []
    for emb in embeddings:
        results.append(EmbeddingResult(
            embedding=emb.tolist(),
            model=model_name,
        ))
    return results


async def embed_with_ollama(
    texts: list[str],
    base_url: str,
    model: str = "nomic-embed-text",
) -> list[EmbeddingResult]:
    """Generate embeddings using Ollama API (single batched request).

    /api/embed accepts a list input (Ollama >= 0.2.6, July 2024) and
    returns all vectors at once — one round trip instead of len(texts).
    """
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/api/embed",
            json={
                "model": model,
                "input": texts,
            },
        )
        response.raise_for_status()
        data = response.json()

    return [
        EmbeddingResult(embedding=emb, model=model)
        for emb in data["embeddings"]
    ]


async def _check_ollama_available(base_url: str) -> bool:
    """Check if Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            return response.status_code == 200
    except Exception:
        return False


async def generate_embeddings(
    texts: list[str],
    provider: str | None = None,
    model: str | None = None,
) -> list[EmbeddingResult]:
    """
    Generate embeddings for texts using the best available method.

    Args:
        texts: List of text strings to embed
        provider: "openai", "ollama", or "local" (None for auto-detect)
        model: Specific model to use

    Returns:
        List of EmbeddingResult objects
    """
    from grimoire.processors.ai_identifier import get_setting_from_db, get_ollama_url

    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        openai_key = await get_setting_from_db("openai_api_key") or ""
    ollama_url = await get_ollama_url()

    # Auto-detect provider
    if provider is None:
        if openai_key:
            provider = "openai"
        elif ollama_url:
            provider = "ollama"
        elif SENTENCE_TRANSFORMERS_AVAILABLE:
            provider = "local"
        else:
            raise ValueError("No embedding provider available")

    if provider == "openai":
        if not openai_key:
            raise ValueError("OpenAI API key not configured")
        return await embed_with_openai(
            texts,
            openai_key,
            model or "text-embedding-3-small",
        )
    elif provider == "ollama":
        if not ollama_url:
            raise ValueError("OLLAMA_BASE_URL not configured")
        return await embed_with_ollama(
            texts,
            ollama_url,
            model or "nomic-embed-text",
        )
    elif provider == "local":
        return embed_with_local(texts, model or "all-MiniLM-L6-v2")
    else:
        raise ValueError(f"Unknown provider: {provider}")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))


def find_similar(
    query_embedding: list[float],
    embeddings: list[tuple[int, list[float]]],  # List of (id, embedding)
    top_k: int = 10,
    threshold: float = 0.0,
) -> list[tuple[int, float]]:
    """
    Find most similar items to a query embedding (in-memory fallback).

    Delegates to search_product_vectors for batched numpy computation
    instead of building arrays pair-by-pair in a Python loop.
    """
    if not embeddings:
        return []
    vectors = {item_id: emb for item_id, emb in embeddings}
    return search_product_vectors(query_embedding, vectors, top_k, threshold)




def build_metadata_preamble(product: Any) -> str:
    """Build a metadata preamble to prepend to extracted text before embedding.

    This ensures the embedding vector captures structured metadata like
    game system, publisher, tags, and themes — not just raw PDF content.
    """
    parts = []

    if product.title:
        parts.append(f"Title: {product.title}")
    if product.game_system:
        parts.append(f"Game System: {product.game_system}")
    if product.publisher:
        parts.append(f"Publisher: {product.publisher}")
    if product.product_type:
        parts.append(f"Type: {product.product_type}")
    if product.author:
        parts.append(f"Author: {product.author}")
    if product.setting:
        parts.append(f"Setting: {product.setting}")
    if product.genre:
        parts.append(f"Genre: {product.genre}")
    if product.series:
        series_str = product.series
        if product.series_order:
            series_str += f" #{product.series_order}"
        parts.append(f"Series: {series_str}")
    if product.level_range_min is not None or product.level_range_max is not None:
        low = product.level_range_min if product.level_range_min is not None else "?"
        high = product.level_range_max if product.level_range_max is not None else "?"
        parts.append(f"Level Range: {low}-{high}")
    if product.description:
        parts.append(f"Description: {product.description}")

    # Parse JSON array fields
    for field_name, label in [("themes", "Themes"), ("content_warnings", "Content Warnings")]:
        raw = getattr(product, field_name, None)
        if raw:
            try:
                items = json.loads(raw)
                if isinstance(items, list) and items:
                    parts.append(f"{label}: {', '.join(str(i) for i in items)}")
            except (json.JSONDecodeError, TypeError):
                pass

    # Include tags if the relationship is already loaded (avoid lazy load in async)
    try:
        product_tags = inspect(product).dict.get("product_tags")
        if product_tags:
            tag_names = []
            for pt in product_tags:
                tag = inspect(pt).dict.get("tag")
                if tag:
                    tag_names.append(tag.name)
            if tag_names:
                parts.append(f"Tags: {', '.join(tag_names)}")
    except Exception:
        pass

    if not parts:
        return ""

    return "\n".join(parts) + "\n\n"


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Split text into overlapping chunks for embedding.

    Args:
        text: Text to chunk
        chunk_size: Target size of each chunk in characters
        overlap: Number of characters to overlap between chunks

    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence end within last 100 chars
            search_start = max(end - 100, start)
            for punct in ['. ', '! ', '? ', '\n\n', '\n']:
                pos = text.rfind(punct, search_start, end)
                if pos > start:
                    end = pos + len(punct)
                    break

        chunks.append(text[start:end].strip())
        start = end - overlap

    return [c for c in chunks if c]


# In-memory cache for product search vectors
_vector_cache: dict[int, list[float]] | None = None


def invalidate_vector_cache():
    """Call when embeddings are added/removed."""
    global _vector_cache
    _vector_cache = None


def search_product_vectors(
    query: list[float],
    product_vectors: dict[int, list[float]],
    top_k: int = 10,
    threshold: float = 0.0,
) -> list[tuple[int, float]]:
    """Fast cosine similarity search using numpy batch computation."""
    if not product_vectors:
        return []

    # Filter to vectors matching query dimension (mixed models produce different sizes)
    query_dim = len(query)
    product_ids = [pid for pid, vec in product_vectors.items() if len(vec) == query_dim]
    if not product_ids:
        return []
    matrix = np.array([product_vectors[pid] for pid in product_ids], dtype=np.float32)
    query_vec = np.array(query, dtype=np.float32)

    # Batch cosine similarity
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vec)
    norms[norms == 0] = 1e-10  # avoid division by zero
    similarities = np.dot(matrix, query_vec) / norms

    # Filter and sort
    results = [
        (product_ids[i], float(similarities[i]))
        for i in range(len(product_ids))
        if similarities[i] >= threshold
    ]
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def get_available_providers() -> dict[str, bool]:
    """Check which embedding providers are available."""
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "ollama": bool(os.getenv("OLLAMA_BASE_URL")),
        "local": SENTENCE_TRANSFORMERS_AVAILABLE,
    }
