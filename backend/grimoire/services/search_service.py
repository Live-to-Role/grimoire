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


# --- Full search flow --------------------------------------------------------

from grimoire.services.embeddings import generate_embeddings  # noqa: E402
from grimoire.services.fts_service import search_fts  # noqa: E402
from grimoire.services.hybrid_search import reciprocal_rank_fusion  # noqa: E402
from grimoire.services.query_interpreter import Interpretation, interpret_query  # noqa: E402


def build_interpreted_conditions(interp: Interpretation) -> list:
    """Lenient conditions for interpreter-derived filters: (== value) OR NULL.
    A misparse or unlabeled product must not vanish silently. Explicit
    FilterDrawer filters stay strict (build_semantic_filter_conditions)."""
    conditions = []
    if interp.game_system:
        conditions.append(
            (Product.game_system == interp.game_system) | (Product.game_system.is_(None))
        )
    if interp.product_type:
        conditions.append(
            (Product.product_type == interp.product_type) | (Product.product_type.is_(None))
        )
    if interp.level_min is not None:
        conditions.append(
            (Product.level_range_max >= interp.level_min) | (Product.level_range_max.is_(None))
        )
    if interp.level_max is not None:
        conditions.append(
            (Product.level_range_min <= interp.level_max) | (Product.level_range_min.is_(None))
        )
    return conditions


async def _allowed_ids(db, conditions: list, request) -> set[int] | None:
    """Evaluate filters SQL-side once; None means unfiltered."""
    from grimoire.models import ProductTag

    extra = list(conditions)
    if request.tags:
        tag_ids = [int(t.strip()) for t in request.tags.split(",") if t.strip()]
        if tag_ids:
            tag_subq = select(ProductTag.product_id).where(ProductTag.tag_id.in_(tag_ids))
            extra.append(Product.id.in_(tag_subq))
    if request.collection:
        from grimoire.models.collection import CollectionProduct
        coll_subq = select(CollectionProduct.product_id).where(
            CollectionProduct.collection_id == request.collection
        )
        extra.append(Product.id.in_(coll_subq))

    if not extra:
        return None
    result = await db.execute(select(Product.id).where(*extra))
    return set(result.scalars().all())


async def search(db, request) -> dict:
    """Two-stage semantic search. request is a SemanticSearchRequest."""
    from sqlalchemy.orm import selectinload
    from grimoire.models import ProductTag
    from grimoire.api.routes.products import product_to_response
    from grimoire.api.routes.semantic import build_semantic_filter_conditions

    # 1. Interpret (explicit drawer filters win over interpreted ones)
    interp: Interpretation | None = None
    semantic_query = request.query
    if getattr(request, "interpret", True):
        interp = await interpret_query(db, request.query)
        if request.game_system:
            interp.game_system = None
        if request.product_type:
            interp.product_type = None
        if request.level_min is not None or request.level_max is not None:
            interp.level_min = None
            interp.level_max = None
        semantic_query = interp.semantic_query or request.query

    # 2. Pre-filter: strict explicit conditions + lenient interpreted ones
    conditions = build_semantic_filter_conditions(request)
    if interp is not None:
        conditions += build_interpreted_conditions(interp)
    allowed = await _allowed_ids(db, conditions, request)

    # 3. Embed the (refined) query
    query_embeddings = await generate_embeddings([semantic_query], None, request.model)
    query_vector = query_embeddings[0].embedding

    # 4. Stage 1 candidates: SV top-N union BM25 top-N
    ids, matrix = await get_sv_index(db)
    sv_candidates = sv_top_candidates(
        query_vector, ids, matrix, allowed, CANDIDATES_PER_SOURCE
    )

    keyword_ranking: list[tuple[int, float]] = []
    try:
        fts_results = await search_fts(
            db, semantic_query,
            game_system=request.game_system,
            product_type=request.product_type,
            limit=CANDIDATES_PER_SOURCE,
        )
        keyword_ranking = [
            (r["id"], r["relevance_score"]) for r in fts_results
            if allowed is None or r["id"] in allowed
        ]
    except Exception:
        logger.warning("FTS failed during search; continuing semantic-only")

    # Zero search vectors anywhere -> pure FTS fallback
    if matrix is None and not sv_candidates:
        candidate_ids = [pid for pid, _ in keyword_ranking]
        semantic_ranking: list[tuple[int, float, str, int | None]] = []
    else:
        candidate_ids = merge_candidates(sv_candidates, keyword_ranking)

        # 5. Stage 2: chunk-level re-rank over candidates only
        per_product = await load_candidate_chunks(db, candidate_ids, len(query_vector))
        reranked = rerank_by_chunks(query_vector, per_product)
        semantic_ranking = [r for r in reranked if r[1] >= CHUNK_SCORE_THRESHOLD]

    best_chunk = {pid: (text, page) for pid, _, text, page in semantic_ranking}

    # 6. Fuse chunk ranking with keyword ranking
    fused = reciprocal_rank_fusion(
        [(pid, score) for pid, score, _, _ in semantic_ranking],
        keyword_ranking,
        semantic_weight=SEMANTIC_RRF_WEIGHT,
        keyword_weight=KEYWORD_RRF_WEIGHT,
    )
    if fused and fused[0][1] > 0:
        top_score = fused[0][1]
        fused = [(pid, s / top_score) for pid, s in fused]

    semantic_ids = {pid for pid, *_ in semantic_ranking}
    keyword_ids = {pid for pid, _ in keyword_ranking}

    matched_ids = [pid for pid, _ in fused][: request.top_k]
    score_map = dict(fused)

    if not matched_ids:
        return {
            "query": request.query,
            "results": [],
            "total_matches": 0,
            "interpretation": interp.to_dict() if interp else None,
        }

    # 7. Hydrate products and build response items
    products_result = await db.execute(
        select(Product)
        .where(Product.id.in_(matched_ids))
        .options(selectinload(Product.product_tags).selectinload(ProductTag.tag))
    )
    products = {p.id: p for p in products_result.scalars().all()}

    results = []
    for pid in matched_ids:
        product = products.get(pid)
        if not product:
            continue
        item = product_to_response(product).model_dump()
        item["score"] = round(score_map[pid], 4)
        chunk_text, page = best_chunk.get(pid, (None, None))
        item["matched_page"] = page
        item["snippet"] = (
            chunk_text[:150] + "..." if chunk_text and len(chunk_text) > 150 else chunk_text
        )
        if pid in semantic_ids and pid in keyword_ids:
            item["match_type"] = "both"
        elif pid in semantic_ids:
            item["match_type"] = "semantic"
        else:
            item["match_type"] = "keyword"
        results.append(item)

    return {
        "query": request.query,
        "results": results,
        "total_matches": len(results),
        "interpretation": interp.to_dict() if interp else None,
    }
