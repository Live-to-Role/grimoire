"""End-to-end search flow with fake embeddings + fake FTS."""
import json

import pytest
from sqlalchemy import delete

from grimoire.models import Product, ProductEmbedding
from grimoire.models.product_search_vector import ProductSearchVector
from grimoire.services import search_service
from grimoire.services.embeddings import EmbeddingResult, invalidate_vector_cache
from grimoire.api.routes.semantic import SemanticSearchRequest

DIM = 4
UNDEAD = [1.0, 0.0, 0.0, 0.0]
BLAND = [0.5, 0.5, 0.5, 0.5]


async def _mk_product(db, hash_, title, level_min=None, level_max=None,
                      sv_vec=None, chunks=()):
    p = Product(file_path=f"/x/{hash_}.pdf", file_name=f"{hash_}.pdf",
                file_size=1024, file_hash=hash_, title=title,
                level_range_min=level_min, level_range_max=level_max)
    db.add(p)
    await db.commit()
    if sv_vec is not None:
        sv = ProductSearchVector(product_id=p.id, embedding_model="fake",
                                 embedding_dim=DIM)
        sv.set_vector(sv_vec)
        db.add(sv)
    for i, (text, vec, page) in enumerate(chunks):
        e = ProductEmbedding(product_id=p.id, chunk_index=i, chunk_text=text,
                             embedding_model="fake", embedding_dim=DIM,
                             page_start=page, page_end=page)
        e.set_embedding_vector(vec)
        db.add(e)
    await db.commit()
    return p


@pytest.fixture
async def fake_search_env(db, monkeypatch):
    """Query embeds to UNDEAD; FTS returns nothing unless a test overrides."""
    # The engine fixture is session-scoped and other test modules (e.g.
    # test_embed_pages.py) persist ProductSearchVector rows of their own
    # dimension without cleaning up. Wipe the table first so the
    # dominant-dimension pick in get_sv_index is deterministic here (see the
    # identical precaution in test_search_service.py).
    await db.execute(delete(ProductSearchVector))
    await db.commit()

    async def fake_embed(texts, provider=None, model=None):
        return [EmbeddingResult(embedding=UNDEAD, model="fake") for _ in texts]

    async def fake_fts(db, query, *, game_system=None, product_type=None, limit=20):
        return []

    monkeypatch.setattr(search_service, "generate_embeddings", fake_embed)
    monkeypatch.setattr(search_service, "fts_candidates", fake_fts)
    # avoid real settings lookup / LLM
    from grimoire.services.query_interpreter import Interpretation

    async def fake_interpret(db, query):
        return Interpretation(semantic_query=query, level_min=3, level_max=3,
                              source="heuristic")

    monkeypatch.setattr(search_service, "interpret_query", fake_interpret)
    invalidate_vector_cache()
    yield
    invalidate_vector_cache()


async def test_chunk_rerank_beats_diluted_average(db, fake_search_env):
    # Book A: bland average but one strongly-undead chunk -> should win
    a = await _mk_product(db, "flow-a", "Tome of Many Things", sv_vec=BLAND, chunks=[
        ("boring intro", BLAND, 1),
        ("the undead crypt of horrors", UNDEAD, 47),
    ])
    # Book B: average closer to query but weak chunks
    b = await _mk_product(db, "flow-b", "Generic Fantasy", sv_vec=[0.8, 0.2, 0.2, 0.2],
                          chunks=[("mild spooky content", [0.6, 0.4, 0.4, 0.4], 2)])

    req = SemanticSearchRequest(query="undead adventure", top_k=5, interpret=True, hybrid=True)
    out = await search_service.search(db, req)

    ids = [r["id"] for r in out["results"]]
    assert ids.index(a.id) < ids.index(b.id)
    top = out["results"][0]
    assert top["matched_page"] == 47
    assert "undead crypt" in top["snippet"]
    assert top["match_type"] in ("semantic", "both")
    assert out["interpretation"]["level_min"] == 3


async def test_interpreted_level_is_not_auto_filtered(db, fake_search_env):
    # Interpreted level is DETECTED but not auto-applied as a filter: sparse level
    # data (only ~16% of the library) would wrongly exclude good topical matches.
    # Both the level-10 book and the unlabeled book must surface; level is opt-in.
    high = await _mk_product(db, "flow-high", "Epic Level 10", 10, 12,
                             sv_vec=UNDEAD, chunks=[("undead epic", UNDEAD, 1)])
    unlabeled = await _mk_product(db, "flow-null", "Mystery Book", None, None,
                                  sv_vec=UNDEAD, chunks=[("undead mystery", UNDEAD, 1)])

    req = SemanticSearchRequest(query="undead for 3rd level", top_k=10, interpret=True)
    out = await search_service.search(db, req)
    ids = [r["id"] for r in out["results"]]
    assert unlabeled.id in ids
    assert high.id in ids  # level 10-12 no longer excluded by the interpreted level
    assert out["interpretation"]["level_min"] == 3  # still detected, just not applied


async def test_bm25_only_product_survives_without_valid_chunks(db, fake_search_env, monkeypatch):
    # Product with no chunks at all (mid re-embed) surfaces via keyword rank
    kw = await _mk_product(db, "flow-kw", "Undead Keyword Hit")

    async def fts_hit(db_, query, *, game_system=None, product_type=None, limit=20):
        return [(kw.id, 9.9)]

    monkeypatch.setattr(search_service, "fts_candidates", fts_hit)
    req = SemanticSearchRequest(query="undead", top_k=10, interpret=False)
    out = await search_service.search(db, req)
    ids = [r["id"] for r in out["results"]]
    assert kw.id in ids
    item = next(r for r in out["results"] if r["id"] == kw.id)
    assert item["match_type"] == "keyword"


async def test_interpret_false_skips_interpretation(db, fake_search_env):
    req = SemanticSearchRequest(query="undead for 3rd level", top_k=5, interpret=False)
    out = await search_service.search(db, req)
    assert out["interpretation"] is None
