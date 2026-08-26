"""A term only in deep body text must reach the results.

This is the failure the whole plan exists to fix: BM25 over the first 50,000
characters could never nominate such a product for Stage 1, so Stage 2 never
saw it, however good the chunk re-rank was.
"""
import pytest

from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import chunk_candidates, index_product_chunks


@pytest.fixture
async def deep_book(db):
    product = Product(
        file_path=r"D:\Games\sf1.pdf",
        file_name="sf1.pdf",
        file_size=1024,
        file_hash="sf1hash",
        title="SF1 Volturnus Planet of Mystery",
        text_extracted=True,
    )
    db.add(product)
    await db.flush()
    # Chunk 400 stands in for text far past the old 50,000-char cap.
    emb = ProductEmbedding(
        product_id=product.id,
        chunk_index=400,
        chunk_text="The Kurabanda live in the treetops of Volturnus.",
        embedding_model="test",
        embedding_dim=3,
        page_start=32,
        page_end=33,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()
    await index_product_chunks(db, product.id)
    await db.commit()
    return product


async def test_body_only_term_produces_a_candidate(db, deep_book):
    hits = await chunk_candidates(db, "Kurabanda")

    assert [pid for pid, _, _, _ in hits] == [deep_book.id]


async def test_the_candidate_carries_snippet_and_page(db, deep_book):
    """Today best_chunk is filled only by the semantic re-rank, so a product
    that surfaces purely on keywords shows no snippet at all."""
    (_, _, snippet, page), = await chunk_candidates(db, "Kurabanda")

    assert "Kurabanda" in snippet
    assert page == 32
