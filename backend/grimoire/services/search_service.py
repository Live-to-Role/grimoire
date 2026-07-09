"""Two-stage semantic search: candidate union (averaged vectors + BM25) then
chunk-level re-rank. See docs/superpowers/specs/2026-07-08-search-accuracy-design.md.
"""

import logging
from collections import OrderedDict

import numpy as np
from sqlalchemy import select

from grimoire.models import Product, ProductEmbedding
from grimoire.models.product_search_vector import ProductSearchVector
from grimoire.services.embeddings import register_invalidation_callback

logger = logging.getLogger(__name__)

# Tunable retrieval constants (adjust via the eval harness, Task 11)
CANDIDATES_PER_SOURCE = 150
MAX_CANDIDATES = 200
TOP_K_CHUNKS = 3
CHUNK_SCORE_THRESHOLD = 0.45
SEMANTIC_RRF_WEIGHT = 1.0
KEYWORD_RRF_WEIGHT = 1.0

# --- Caches ----------------------------------------------------------------

_sv_index: tuple[list[int], np.ndarray | None] | None = None
_chunk_cache: OrderedDict = OrderedDict()  # (product_id, dim) -> (matrix, meta)
_CHUNK_CACHE_MAX = 300


def _clear_caches() -> None:
    global _sv_index
    _sv_index = None
    _chunk_cache.clear()


register_invalidation_callback(_clear_caches)


async def get_sv_index(db) -> tuple[list[int], np.ndarray | None]:
    """All product search vectors as (ids, float32 matrix), cached in memory.

    ~12.7k x 768 floats is ~39 MB — cheap to hold, expensive to reload from
    SQLite per search (which is what the old route did).
    """
    global _sv_index
    if _sv_index is not None:
        return _sv_index

    result = await db.execute(select(ProductSearchVector))
    svs = result.scalars().all()
    if not svs:
        _sv_index = ([], None)
        return _sv_index

    # Group by dim, keep the dominant dimension (mixed models mid-re-embed)
    ids = [sv.product_id for sv in svs]
    vectors = [sv.get_vector() for sv in svs]
    dims = [len(v) for v in vectors]
    dominant = max(set(dims), key=dims.count)
    filtered = [(i, v) for i, v, d in zip(ids, vectors, dims) if d == dominant]
    ids = [i for i, _ in filtered]
    matrix = np.array([v for _, v in filtered], dtype=np.float32)
    _sv_index = (ids, matrix)
    return _sv_index


def sv_top_candidates(
    query_vector: list[float],
    ids: list[int],
    matrix: np.ndarray | None,
    allowed_ids: set[int] | None,
    limit: int,
) -> list[tuple[int, float]]:
    """Cosine top-N over the SV matrix, restricted to allowed_ids. No threshold."""
    if matrix is None or not ids or matrix.shape[1] != len(query_vector):
        return []

    q = np.array(query_vector, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
    norms[norms == 0] = 1e-10
    sims = matrix @ q / norms

    pairs = (
        (pid, float(s)) for pid, s in zip(ids, sims)
        if allowed_ids is None or pid in allowed_ids
    )
    return sorted(pairs, key=lambda x: x[1], reverse=True)[:limit]


def chunk_score(similarities: np.ndarray, top_k: int = TOP_K_CHUNKS) -> float:
    """Product relevance from its chunk similarities: mean of the top-k
    (all of them when fewer than k). Rewards focused topical hits without
    letting one noisy chunk dominate."""
    if similarities.size == 0:
        return 0.0
    k = min(top_k, similarities.size)
    top = np.partition(similarities, -k)[-k:]
    return float(np.mean(top))


async def load_candidate_chunks(
    db, product_ids: list[int], query_dim: int
) -> dict[int, tuple[np.ndarray, list[tuple[str, int | None]]]]:
    """Chunk vectors for candidate products only, dimension-filtered, with a
    bounded LRU cache keyed by (product_id, dim). meta is [(chunk_text,
    page_start), ...] aligned with matrix rows."""
    out: dict[int, tuple[np.ndarray, list[tuple[str, int | None]]]] = {}
    missing: list[int] = []
    for pid in product_ids:
        key = (pid, query_dim)
        if key in _chunk_cache:
            _chunk_cache.move_to_end(key)
            out[pid] = _chunk_cache[key]
        else:
            missing.append(pid)

    if missing:
        result = await db.execute(
            select(ProductEmbedding).where(
                ProductEmbedding.product_id.in_(missing),
                ProductEmbedding.embedding_dim == query_dim,
            )
        )
        rows_by_pid: dict[int, list[ProductEmbedding]] = {}
        for row in result.scalars().all():
            rows_by_pid.setdefault(row.product_id, []).append(row)

        for pid in missing:
            rows = rows_by_pid.get(pid, [])
            if rows:
                matrix = np.array(
                    [r.get_embedding_vector() for r in rows], dtype=np.float32
                )
                meta = [(r.chunk_text, r.page_start) for r in rows]
            else:
                matrix = np.empty((0, query_dim), dtype=np.float32)
                meta = []
            entry = (matrix, meta)
            _chunk_cache[(pid, query_dim)] = entry
            while len(_chunk_cache) > _CHUNK_CACHE_MAX:
                _chunk_cache.popitem(last=False)
            out[pid] = entry

    return out


def rerank_by_chunks(
    query_vector: list[float],
    per_product: dict[int, tuple[np.ndarray, list[tuple[str, int | None]]]],
) -> list[tuple[int, float, str, int | None]]:
    """Score candidates by their best chunks. Returns (product_id, score,
    best_chunk_text, best_page) sorted by score desc. Products with no valid
    chunks are omitted (they can still surface via BM25)."""
    q = np.array(query_vector, dtype=np.float32)
    qn = np.linalg.norm(q)
    ranked = []
    for pid, (matrix, meta) in per_product.items():
        if matrix.shape[0] == 0:
            continue
        norms = np.linalg.norm(matrix, axis=1) * qn
        norms[norms == 0] = 1e-10
        sims = matrix @ q / norms
        best_idx = int(np.argmax(sims))
        ranked.append((pid, chunk_score(sims), meta[best_idx][0], meta[best_idx][1]))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def merge_candidates(
    sv_list: list[tuple[int, float]],
    bm25_list: list[tuple[int, float]],
    cap: int = MAX_CANDIDATES,
) -> list[int]:
    """Union of candidate sources: every SV candidate, remainder filled from
    BM25 in rank order, deduped, capped."""
    seen: set[int] = set()
    merged: list[int] = []
    for pid, _ in sv_list:
        if pid not in seen:
            seen.add(pid)
            merged.append(pid)
    for pid, _ in bm25_list:
        if len(merged) >= cap:
            break
        if pid not in seen:
            seen.add(pid)
            merged.append(pid)
    return merged[:cap]
