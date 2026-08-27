"""Writing a product's chunks into the body index.

The index mirrors product_embeddings.chunk_text, which is the full document:
chunks cap at 500 characters and overlap, so nothing is truncated the way the
old 50,000-character products_fts body was.
"""
import pytest
from sqlalchemy import text

from grimoire.database import _ensure_fts_table
from grimoire.models import Product, ProductEmbedding
from grimoire.services.fts_service import (
    clear_product_chunk_index,
    index_product_chunks,
)


@pytest.fixture
async def chunked_product(db):
    await _ensure_fts_table(await db.connection())
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

    for i, (body, ps, pe) in enumerate([
        ("The party lands on Volturnus in a damaged shuttle.", 1, 2),
        ("The Kurabanda live in the treetops and fear the Sathar.", 32, 33),
        ("Alcazzar holds the robot foundry beneath the sand.", 35, 36),
    ]):
        emb = ProductEmbedding(
            product_id=product.id,
            chunk_index=i,
            chunk_text=body,
            embedding_model="test",
            embedding_dim=3,
            page_start=ps,
            page_end=pe,
        )
        emb.set_embedding_vector([0.1, 0.2, 0.3])
        db.add(emb)
    await db.commit()
    return product


async def _match(db, term: str) -> list[tuple]:
    rows = (await db.execute(text(
        "SELECT product_id, chunk_index, page_start, page_end"
        " FROM product_chunks_fts WHERE product_chunks_fts MATCH :q"
        " ORDER BY chunk_index"
    ), {"q": term})).all()
    return [tuple(r) for r in rows]


async def test_index_writes_one_row_per_chunk(db, chunked_product):
    written = await index_product_chunks(db, chunked_product.id)
    assert written == 3


async def test_a_term_deep_in_the_document_is_findable(db, chunked_product):
    """The whole point: page 32 is past where the old 50k cap would have cut."""
    await index_product_chunks(db, chunked_product.id)

    hits = await _match(db, "Kurabanda")
    assert hits == [(chunked_product.id, 1, 32, 33)]


async def test_page_numbers_come_back_with_the_hit(db, chunked_product):
    """UNINDEXED columns travel with the match, so no join is needed."""
    await index_product_chunks(db, chunked_product.id)

    (_, _, page_start, page_end), = await _match(db, "Alcazzar")
    assert (page_start, page_end) == (35, 36)


async def test_reindexing_replaces_rather_than_duplicates(db, chunked_product):
    await index_product_chunks(db, chunked_product.id)
    await clear_product_chunk_index(db, chunked_product.id)
    await index_product_chunks(db, chunked_product.id)

    assert len(await _match(db, "Kurabanda")) == 1


async def test_clear_removes_only_this_product(db, chunked_product):
    other = Product(
        file_path=r"D:\Games\other.pdf",
        file_name="other.pdf",
        file_size=1024,
        file_hash="otherhash",
        title="Other Book",
        text_extracted=True,
    )
    db.add(other)
    await db.flush()
    emb = ProductEmbedding(
        product_id=other.id,
        chunk_index=0,
        chunk_text="The Kurabanda appear here too.",
        embedding_model="test",
        embedding_dim=3,
        page_start=1,
        page_end=1,
    )
    emb.set_embedding_vector([0.1, 0.2, 0.3])
    db.add(emb)
    await db.commit()

    await index_product_chunks(db, chunked_product.id)
    await index_product_chunks(db, other.id)
    await clear_product_chunk_index(db, chunked_product.id)

    hits = await _match(db, "Kurabanda")
    assert [h[0] for h in hits] == [other.id]
