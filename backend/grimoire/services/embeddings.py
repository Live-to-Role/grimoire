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
    embeddings = model.encode(texts, convert_to_numpy=True)

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
    """Generate embeddings using Ollama API."""
    results = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for text in texts:
            response = await client.post(
                f"{base_url.rstrip('/')}/api/embed",
                json={
                    "model": model,
                    "input": text,
                },
            )
            response.raise_for_status()
            data = response.json()
            results.append(EmbeddingResult(
                embedding=data["embeddings"][0],
                model=model,
            ))
    return results


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

    Args:
        query_embedding: The query vector
        embeddings: List of (id, embedding) tuples to search
        top_k: Number of results to return
        threshold: Minimum similarity score

    Returns:
        List of (id, similarity_score) tuples, sorted by score descending
    """
    scores = []
    for item_id, emb in embeddings:
        score = cosine_similarity(query_embedding, emb)
        if score >= threshold:
            scores.append((item_id, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_k]




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

    product_ids = list(product_vectors.keys())
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
