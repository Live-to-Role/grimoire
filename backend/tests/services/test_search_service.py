"""Search service primitives: scoring, candidate merge, caches."""
import numpy as np
import pytest
from sqlalchemy import delete

from grimoire.models import Product, ProductEmbedding
from grimoire.models.product_search_vector import ProductSearchVector
from grimoire.services import search_service
from grimoire.services.embeddings import invalidate_vector_cache
from grimoire.services.search_service import (
    chunk_score,
    merge_candidates,
    rerank_by_chunks,
    sv_top_candidates,
)


def test_chunk_score_top3_mean():
    sims = np.array([0.9, 0.1, 0.8, 0.7, 0.2])
    assert chunk_score(sims, top_k=3) == pytest.approx((0.9 + 0.8 + 0.7) / 3)


def test_chunk_score_fewer_than_k_uses_all():
    assert chunk_score(np.array([0.6, 0.4]), top_k=3) == pytest.approx(0.5)


def test_sv_top_candidates_restricts_and_ranks():
    ids = [1, 2, 3]
    matrix = np.array([[1, 0], [0, 1], [0.9, 0.1]], dtype=np.float32)
    query = [1.0, 0.0]
    out = sv_top_candidates(query, ids, matrix, allowed_ids={1, 3}, limit=10)
    assert [pid for pid, _ in out] == [1, 3]  # 2 filtered out; ranked by cosine
    out_all = sv_top_candidates(query, ids, matrix, allowed_ids=None, limit=2)
    assert len(out_all) == 2 and out_all[0][0] == 1


def test_merge_candidates_sv_first_then_bm25_fill():
    sv = [(1, 0.9), (2, 0.8)]
    bm25 = [(2, 5.0), (3, 4.0), (4, 3.0)]
    assert merge_candidates(sv, bm25, cap=3) == [1, 2, 3]


def test_rerank_by_chunks_orders_and_reports_best_chunk():
    q = [1.0, 0.0]
    per_product = {
        # both of 7's chunks are strongly aligned with q (mean-of-top-k
        # aggregation), so 7 outranks 8's single moderately-aligned chunk
        7: (np.array([[0.9, 0.1], [0.95, 0.05]], dtype=np.float32),
            [("weak chunk", None), ("strong chunk", 12)]),
        8: (np.array([[0.5, 0.5]], dtype=np.float32), [("meh", 3)]),
    }
    ranked = rerank_by_chunks(q, per_product)
    assert ranked[0][0] == 7
    assert ranked[0][2] == "strong chunk"
    assert ranked[0][3] == 12


async def test_sv_index_cached_and_invalidated(db):
    # The engine fixture is session-scoped, and other test modules (e.g.
    # test_embed_pages.py) persist ProductSearchVector rows of their own
    # dimension without cleaning up. Wipe the table first so the
    # dominant-dimension pick in get_sv_index is deterministic here.
    await db.execute(delete(ProductSearchVector))
    await db.commit()

    # unique products for this test
    p1 = Product(file_path="/x/sv1.pdf", file_name="sv1.pdf", file_size=1024, file_hash="svc-1")
    p2 = Product(file_path="/x/sv2.pdf", file_name="sv2.pdf", file_size=1024, file_hash="svc-2")
    db.add_all([p1, p2])
    await db.commit()

    for p, vec in [(p1, [1.0, 0.0]), (p2, [0.0, 1.0])]:
        sv = ProductSearchVector(product_id=p.id, embedding_model="fake", embedding_dim=2)
        sv.set_vector(vec)
        db.add(sv)
    await db.commit()

    invalidate_vector_cache()  # start clean
    ids, matrix = await search_service.get_sv_index(db)
    assert p1.id in ids and p2.id in ids

    # add another SV; cached index must NOT see it until invalidation
    p3 = Product(file_path="/x/sv3.pdf", file_name="sv3.pdf", file_size=1024, file_hash="svc-3")
    db.add(p3)
    await db.commit()
    sv3 = ProductSearchVector(product_id=p3.id, embedding_model="fake", embedding_dim=2)
    sv3.set_vector([0.5, 0.5])
    db.add(sv3)
    await db.commit()

    ids2, _ = await search_service.get_sv_index(db)
    assert p3.id not in ids2  # served from cache
    invalidate_vector_cache()
    ids3, _ = await search_service.get_sv_index(db)
    assert p3.id in ids3  # callback cleared the cache

    # cleanup so other tests' SV counts aren't polluted
    await db.execute(delete(ProductSearchVector).where(
        ProductSearchVector.product_id.in_([p1.id, p2.id, p3.id])))
    await db.commit()
    invalidate_vector_cache()


async def test_load_candidate_chunks_filters_dimension(db):
    p = Product(file_path="/x/ch1.pdf", file_name="ch1.pdf", file_size=1024, file_hash="svc-ch-1")
    db.add(p)
    await db.commit()

    good = ProductEmbedding(product_id=p.id, chunk_index=0, chunk_text="good",
                            embedding_model="fake", embedding_dim=2, page_start=4, page_end=4)
    good.set_embedding_vector([1.0, 0.0])
    stale = ProductEmbedding(product_id=p.id, chunk_index=1, chunk_text="stale",
                             embedding_model="old", embedding_dim=3)
    stale.set_embedding_vector([1.0, 0.0, 0.0])
    db.add_all([good, stale])
    await db.commit()

    invalidate_vector_cache()
    per = await search_service.load_candidate_chunks(db, [p.id], query_dim=2)
    matrix, meta = per[p.id]
    assert matrix.shape == (1, 2)          # stale 3-dim chunk excluded
    assert meta == [("good", 4)]
